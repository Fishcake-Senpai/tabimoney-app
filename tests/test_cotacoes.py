"""Cotações: brapi como fonte principal, Yahoo de reserva e para completar o histórico antigo."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import db
from app.providers import yahoo
from app.providers.brapi import BrapiError
from app.services import sync

B3 = ZoneInfo("America/Sao_Paulo")


def stamp(day: str) -> int:
    return int(datetime.combine(date.fromisoformat(day), time(10), B3).timestamp())


def chart(points: dict[str, float], splits: dict[str, tuple[int, int]] | None = None) -> dict:
    return {"chart": {"result": [{
        "meta": {"symbol": "TEST3.SA"},
        "timestamp": [stamp(d) for d in points],
        "events": {"splits": {str(stamp(d)): {"date": stamp(d), "numerator": n, "denominator": m}
                              for d, (n, m) in (splits or {}).items()}},
        "indicators": {"quote": [{"close": list(points.values())}]},
    }], "error": None}}


@pytest.fixture
def carteira():
    with db.transaction() as con:
        con.execute(
            "INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
            "VALUES (1, 'Fictício', 'Corretora', 'INVESTMENT', 'manual', 'invest')"
        )
        con.execute("INSERT INTO instrument(id, ticker, name, asset_class) VALUES (1, 'TEST3', 'Fictícia', 'Ação')")
        con.execute(
            "INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
            "VALUES (1, 1, 'manual', '2025-01-02', 1000000)"
        )


def quotes():
    return db.rows("SELECT trade_date, close_cents, provider FROM daily_quote ORDER BY trade_date, provider")


# ---------------------------------------------------------------- provedor

def test_yahoo_desfaz_ajuste_de_desdobramento(monkeypatch):
    seen = {}

    def get(url, params, headers, timeout):
        seen["url"] = url
        # o Yahoo devolve o preço anterior ao desdobramento 2:1 já dividido por 2
        return httpx.Response(200, json=chart({"2025-01-02": 5.0, "2025-01-03": 5.5, "2025-01-06": 11.2},
                                              splits={"2025-01-03": (2, 1)}), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    history = yahoo.daily_history("test3", date(2025, 1, 1), date(2025, 1, 10))
    assert seen["url"].endswith("/TEST3.SA")
    assert history == [("2025-01-02", 1000), ("2025-01-03", 550), ("2025-01-06", 1120)]
    assert yahoo.symbol("^BVSP") == "^BVSP"


def test_yahoo_sem_rede_vira_erro_tratavel():
    with pytest.raises(yahoo.YahooError):
        yahoo.daily_history("TEST3", date(2025, 1, 1))  # a rede está desligada nos testes


def test_yahoo_ativo_inexistente(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        404, json={"chart": {"result": None, "error": {"code": "Not Found"}}}, request=httpx.Request("GET", url)))
    with pytest.raises(yahoo.YahooError, match="não encontrado"):
        yahoo.daily_history("XXXX9", date(2025, 1, 1))


# ---------------------------------------------------------------- atualização de mercado

@pytest.fixture
def mercado(monkeypatch):
    """brapi e Yahoo simulados; anota quem foi chamado e com que período."""
    calls = {"yahoo": []}
    state = {"brapi": lambda ticker: [("2026-10-05", 2000), ("2026-10-06", 2100)], "yahoo": {}}

    def brapi(ticker, token):
        result = state["brapi"](ticker)
        if isinstance(result, Exception):
            raise result
        return result

    def yahoo_history(ticker, start, end=None):
        calls["yahoo"].append((ticker, start, end))
        rows = [(d, c) for d, c in state["yahoo"].get(ticker, []) if start.isoformat() <= d and (not end or d <= end.isoformat())]
        if not rows:
            raise yahoo.YahooError(f"{ticker}: nada")
        return rows

    monkeypatch.setattr(sync, "_fetch_history", brapi)
    monkeypatch.setattr(sync.yahoo, "daily_history", yahoo_history)
    monkeypatch.setattr(sync, "cdi_daily_rates", lambda since: [])
    return state, calls


def test_brapi_recusou_entra_o_yahoo(carteira, mercado):
    state, _ = mercado
    state["brapi"] = lambda ticker: BrapiError(f"{ticker}: o plano/token brapi não permite essa consulta.")
    state["yahoo"]["TEST3"] = [("2025-01-02", 1000), ("2026-10-06", 2100)]
    state["yahoo"]["^BVSP"] = [("2026-10-06", 14500000)]
    result = sync.sync_daily_quotes()
    assert result["status"] == "success"
    assert "1 pelo Yahoo" in result["message"]
    assert [dict(r) for r in quotes()] == [
        {"trade_date": "2025-01-02", "close_cents": 1000, "provider": "yahoo"},
        {"trade_date": "2026-10-06", "close_cents": 2100, "provider": "yahoo"},
    ]


def test_brapi_e_yahoo_falharam_avisa_as_duas(carteira, mercado):
    state, _ = mercado
    state["brapi"] = lambda ticker: BrapiError(f"{ticker}: limite de consultas brapi atingido.")
    result = sync.sync_daily_quotes()
    assert result["status"] == "failed"
    assert "brapi" in result["message"] and "Reserva: TEST3: nada" in result["message"]


def test_yahoo_completa_o_historico_antigo_e_a_brapi_vale_no_mesmo_dia(carteira, mercado):
    state, calls = mercado
    state["yahoo"]["TEST3"] = [("2025-01-02", 1000), ("2026-01-02", 1500), ("2026-10-05", 1999)]
    sync.sync_daily_quotes()
    assert calls["yahoo"][0] == ("TEST3", date(2025, 1, 2), date(2026, 10, 5))
    assert [(r["trade_date"], r["provider"]) for r in quotes()] == [
        ("2025-01-02", "yahoo"), ("2026-01-02", "yahoo"), ("2026-10-05", "brapi"), ("2026-10-06", "brapi"),
    ]
    from app.services import analytics
    book = analytics.Book()
    assert book.close_at(1, "2026-10-05") == 2000  # a brapi vale sobre o Yahoo
    # já completo: a próxima atualização não volta ao Yahoo
    calls["yahoo"].clear()
    sync.sync_daily_quotes()
    assert [c for c in calls["yahoo"] if c[0] == "TEST3"] == []


def test_ibovespa_tambem_tem_reserva(carteira, mercado):
    state, _ = mercado
    state["brapi"] = lambda ticker: (BrapiError("^BVSP: limite") if ticker == "^BVSP"
                                     else [("2025-01-02", 1000), ("2026-10-06", 2100)])
    state["yahoo"]["^BVSP"] = [("2025-01-02", 12000000), ("2026-10-06", 14500000)]
    assert sync.sync_daily_quotes()["status"] == "success"
    ibov = db.rows("SELECT trade_date, value, provider FROM benchmark_quote WHERE code = 'IBOV' ORDER BY trade_date")
    assert [(r["trade_date"], r["value"], r["provider"]) for r in ibov] == [
        ("2025-01-02", 120000.0, "yahoo"), ("2026-10-06", 145000.0, "yahoo"),
    ]


# ---------------------------------------------------------------- fundamentos

def test_fundamentos_sem_brapi_usam_cotacao_guardada_e_acoes_da_cvm(carteira, monkeypatch):
    from app.providers import cvm
    from app.services import fundamentals

    with db.transaction() as con:
        con.execute("INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
                    "VALUES (1, '2026-10-06', 2500, 'yahoo')")
    company = cvm.Company(cnpj="1", name="Fictícia SA", sector="Energia")
    quarter = cvm.Quarter(period_end="2026-06-30", values={"shares": 1_000_000_000, "net_income": 1e8})
    monkeypatch.setattr(cvm, "companies_by_ticker", lambda tickers: {"TEST3": company})
    monkeypatch.setattr(cvm, "statements_by_company", lambda *a, **k: ({"1": [quarter]}, [], {}))
    fundamentals.sync_fundamentals()  # a brapi não responde: rede desligada
    profile = db.rows("SELECT market_cap_cents, shares_outstanding FROM company_profile WHERE instrument_id = 1")[0]
    assert profile["shares_outstanding"] == 1_000_000_000
    assert profile["market_cap_cents"] == 25 * 1_000_000_000 * 100
