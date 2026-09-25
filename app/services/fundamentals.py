"""Fundamentos das empresas da carteira: coleta, indicadores, avisos e o contrato com o agente de IA.

Camadas (todas em SQLite, formato padronizado):
- company_profile: ticker → empresa (CNPJ, setor, descrição, valor de mercado).
- fundamental_metric: métricas em formato longo (instrumento, fim do período, tipo de período, métrica, valor,
  origem). A CVM grava os valores trimestrais brutos (source='cvm'); os indicadores (P/L, ROE…) são calculados
  na leitura com o preço do dia. Um agente grava as suas métricas com a própria origem (source='agente').
- company_filing: ITR/DFP entregues à CVM, com link para o documento.
- analysis_report e fundamental_alert: relatórios e avisos (regras automáticas ou agente).

O formato de entrada do agente está em docs/agente-financeiro.md e é validado por import_analysis().
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import httpx

from app.db import rows, set_setting, get_setting, transaction
from app.providers import cvm
from app.security import get_secret

CVM_METRICS = {
    "revenue": "R$", "ebit": "R$", "net_income": "R$", "net_income_total": "R$", "da": "R$", "cfo": "R$",
    "capex": "R$", "dividends_paid": "R$", "total_assets": "R$", "equity": "R$", "equity_parent": "R$",
    "cash": "R$", "debt": "R$", "shares": "ações",
}
FINANCIAL_SECTORS = re.compile(r"banco|segur|intermedia|previd|arrendamento|credito", re.IGNORECASE)
YEARS_BACK = 3
SEVERITY_ORDER = {"critico": 0, "atencao": 1, "info": 2, "positivo": 3}

# Indicadores exibidos: chave → (rótulo, formato, explicação curta). Formatos: pct, x (múltiplo), brl.
INDICATORS = {
    "pl": ("P/L", "x", "Preço ÷ lucro dos últimos 12 meses"),
    "pvp": ("P/VP", "x", "Preço ÷ patrimônio líquido"),
    "ev_ebit": ("EV/EBIT", "x", "Valor da firma ÷ lucro operacional 12M"),
    "ev_ebitda": ("EV/EBITDA", "x", "Valor da firma ÷ EBITDA 12M"),
    "dy": ("Dividend yield", "pct", "Dividendos/JCP pagos pela empresa em 12M ÷ valor de mercado"),
    "payout": ("Payout", "pct", "Dividendos pagos ÷ lucro 12M"),
    "roe": ("ROE", "pct", "Lucro 12M ÷ patrimônio médio"),
    "roa": ("ROA", "pct", "Lucro 12M ÷ ativo total"),
    "net_margin": ("Margem líquida", "pct", "Lucro ÷ receita, 12M"),
    "ebit_margin": ("Margem EBIT", "pct", "Lucro operacional ÷ receita, 12M"),
    "net_debt_ebitda": ("Dív. líq./EBITDA", "x", "Anos de geração de caixa para pagar a dívida"),
    "net_debt_equity": ("Dív. líq./PL", "x", "Alavancagem sobre o patrimônio"),
    "revenue_growth": ("Receita 12M a/a", "pct", "Crescimento da receita 12M contra um ano antes"),
    "earnings_growth": ("Lucro 12M a/a", "pct", "Crescimento do lucro 12M contra um ano antes"),
    "fcf_yield": ("FCF yield", "pct", "(Caixa operacional − capex) 12M ÷ valor de mercado"),
}
FINANCIAL_HIDDEN = {"ev_ebit", "ev_ebitda", "ebit_margin", "net_debt_ebitda", "net_debt_equity", "fcf_yield"}


class FundamentalsError(RuntimeError):
    pass


def _n(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def _p(value: float, places: int = 0) -> str:
    return _n(value * 100, places) + "%"


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


# ---------------------------------------------------------------- coleta

def _brapi_quote(ticker: str, token: str | None) -> dict[str, Any]:
    """Campos do plano gratuito: valor de mercado, P/L, setor e descrição (summaryProfile)."""
    params: dict[str, str] = {"modules": "summaryProfile", "fundamental": "true"}
    if token:
        params["token"] = token
    try:
        response = httpx.get(f"https://brapi.dev/api/quote/{ticker}", params=params, timeout=30)
    except httpx.HTTPError:
        return {}
    if response.status_code != 200:
        return {}
    try:
        result = response.json()["results"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return {}
    return result if isinstance(result, dict) else {}


def _companies_in_portfolio() -> list[dict[str, Any]]:
    """Ativos com posição ou eventos; a CVM decide quem é empresa (ETFs e FIIs não estão no cadastro de cias)."""
    return [dict(r) for r in rows(
        "SELECT DISTINCT i.id, i.ticker, i.name, i.asset_class FROM instrument i "
        "WHERE i.id IN (SELECT instrument_id FROM position_snapshot) OR i.id IN (SELECT instrument_id FROM investment_event) "
        "ORDER BY i.ticker"
    )]


def sync_fundamentals(tickers: list[str] | None = None) -> dict[str, Any]:
    """Atualiza cadastro (CVM), demonstrações trimestrais (CVM), mercado (brapi) e os avisos por regras."""
    instruments = _companies_in_portfolio()
    if tickers:
        wanted = {t.upper() for t in tickers}
        instruments = [i for i in instruments if i["ticker"].upper() in wanted]
    if not instruments:
        return {"companies": 0, "message": "Nenhum ativo na carteira."}
    by_ticker = {i["ticker"].upper(): i for i in instruments}
    try:
        companies = cvm.companies_by_ticker(set(by_ticker))
    except cvm.CvmError as exc:
        raise FundamentalsError(str(exc)) from exc
    if not companies:
        return {"companies": 0, "message": "Nenhum ativo da carteira é companhia aberta (ETFs e FIIs ficam de fora)."}
    this_year = date.today().year
    try:
        series, filings = cvm.statements_by_company(
            {c.cnpj for c in companies.values()}, list(range(this_year - YEARS_BACK, this_year + 1))
        )
    except cvm.CvmError as exc:
        raise FundamentalsError(str(exc)) from exc
    try:
        token = get_secret("brapi_token")
    except Exception:
        token = None
    now = datetime.now().isoformat(timespec="seconds")
    written = 0
    with transaction() as connection:
        for ticker, company in companies.items():
            instrument_id = int(by_ticker[ticker]["id"])
            quarters = series.get(company.cnpj, [])
            quote = _brapi_quote(ticker, token)
            profile = quote.get("summaryProfile") if isinstance(quote.get("summaryProfile"), dict) else {}
            financial = bool(FINANCIAL_SECTORS.search(company.sector or "")) or any(q.is_financial for q in quarters[-4:])
            market_cap = quote.get("marketCap")
            price = quote.get("regularMarketPrice")
            shares = int(market_cap / price) if market_cap and price else None
            per_unit = company.shares_per_unit.get(ticker)
            cvm_shares = next((q.values["shares"] for q in reversed(quarters) if q.values.get("shares")), None)
            if per_unit and cvm_shares:
                # unit = pacote de ações: o valor de mercado é preço da unit × (ações ÷ ações por unit)
                cvm_shares = cvm_shares * 1000 if cvm_shares < 20_000_000 else cvm_shares
                shares = int(cvm_shares / per_unit)
                market_cap = price * shares if price else None
            connection.execute(
                "INSERT INTO company_profile(instrument_id, cnpj, cvm_code, company_name, sector, industry, summary, "
                "is_financial, market_cap_cents, shares_outstanding, price_earnings, market_updated_at, statements_updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(instrument_id) DO UPDATE SET "
                "cnpj = excluded.cnpj, cvm_code = excluded.cvm_code, company_name = excluded.company_name, "
                "sector = COALESCE(excluded.sector, company_profile.sector), "
                "industry = COALESCE(excluded.industry, company_profile.industry), "
                "summary = COALESCE(excluded.summary, company_profile.summary), is_financial = excluded.is_financial, "
                "market_cap_cents = COALESCE(excluded.market_cap_cents, company_profile.market_cap_cents), "
                "shares_outstanding = COALESCE(excluded.shares_outstanding, company_profile.shares_outstanding), "
                "price_earnings = COALESCE(excluded.price_earnings, company_profile.price_earnings), "
                "market_updated_at = COALESCE(excluded.market_updated_at, company_profile.market_updated_at), "
                "statements_updated_at = excluded.statements_updated_at",
                (instrument_id, company.cnpj, company.cvm_code, company.name,
                 profile.get("sectorDisp") or profile.get("sector") or company.sector,
                 profile.get("industryDisp") or profile.get("industry"),
                 (profile.get("longBusinessSummary") or "")[:4000] or None,
                 1 if financial else 0,
                 int(round(market_cap * 100)) if market_cap else None, shares,
                 quote.get("priceEarnings"), now if market_cap else None, now),
            )
            for quarter in quarters:
                for metric, value in quarter.values.items():
                    if metric == "shares" and value < 20_000_000:
                        value *= 1000  # parte das empresas informa a composição do capital em milhares
                    connection.execute(
                        "INSERT INTO fundamental_metric(instrument_id, period_end, period_type, metric, value, unit, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'cvm') ON CONFLICT(instrument_id, period_end, period_type, metric, source) "
                        "DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                        (instrument_id, quarter.period_end, "SNAPSHOT" if metric in cvm.STOCK_KEYS else "Q",
                         metric, value, CVM_METRICS.get(metric)),
                    )
                    written += 1
            for filing in filings:
                if filing.cnpj == company.cnpj:
                    connection.execute(
                        "INSERT INTO company_filing(instrument_id, period_end, doc_type, version, received_at, link) "
                        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(instrument_id, period_end, doc_type) DO UPDATE SET "
                        "version = excluded.version, received_at = excluded.received_at, link = excluded.link",
                        (instrument_id, filing.period_end, filing.doc_type, filing.version, filing.received_at, filing.link),
                    )
    alerts = refresh_rule_alerts()
    set_setting("fundamentals_synced_at", now)
    return {"companies": len(companies), "metrics": written, "alerts": alerts,
            "message": f"{len(companies)} empresa(s) atualizadas pela CVM; {alerts} aviso(s) ativo(s)."}


def auto_sync_weekly() -> None:
    """Chamado pelo agendador: a CVM publica novidades semanalmente."""
    last = get_setting("fundamentals_synced_at")
    if last and (datetime.now() - datetime.fromisoformat(last)).days < 7:
        return
    try:
        sync_fundamentals()
    except Exception:
        set_setting("fundamentals_synced_at", datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------- leitura e indicadores

def _series(instrument_id: int, source: str = "cvm") -> dict[str, dict[str, float]]:
    """{period_end: {métrica: valor}} com fluxos trimestrais e saldos na data."""
    out: dict[str, dict[str, float]] = {}
    for r in rows(
        "SELECT period_end, metric, value FROM fundamental_metric WHERE instrument_id = ? AND source = ? "
        "AND period_type IN ('Q', 'SNAPSHOT') ORDER BY period_end", (instrument_id, source),
    ):
        if r["value"] is not None:
            out.setdefault(r["period_end"], {})[r["metric"]] = float(r["value"])
    return out


def _ttm(periods: list[str], data: dict[str, dict[str, float]], index: int, key: str) -> float | None:
    if index < 3:
        return None
    values = [data[periods[i]].get(key) for i in range(index - 3, index + 1)]
    return sum(values) if all(v is not None for v in values) else None


def quarterly_table(instrument_id: int, financial: bool) -> list[dict[str, Any]]:
    """Um registro por trimestre, com os fluxos do trimestre e os indicadores 12M daquela data."""
    data = _series(instrument_id)
    periods = sorted(data)
    table = []
    for index, period in enumerate(periods):
        row = dict(data[period])
        ni_ttm = _ttm(periods, data, index, "net_income")
        revenue_ttm = _ttm(periods, data, index, "revenue")
        ebit_ttm = _ttm(periods, data, index, "ebit")
        da_ttm = _ttm(periods, data, index, "da")
        equity_now = row.get("equity_parent")
        equity_prev = data[periods[index - 4]].get("equity_parent") if index >= 4 else None
        equity_avg = (equity_now + equity_prev) / 2 if equity_now and equity_prev else equity_now
        net_debt = (row.get("debt") or 0) - (row.get("cash") or 0) if ("debt" in row or "cash" in row) and not financial else None
        ebitda_ttm = ebit_ttm + da_ttm if ebit_ttm is not None and da_ttm is not None else ebit_ttm
        row.update({
            "period_end": period, "label": f"{int(period[5:7]) // 3}T{period[2:4]}",
            "net_income_ttm": ni_ttm, "revenue_ttm": revenue_ttm, "ebit_ttm": ebit_ttm, "ebitda_ttm": ebitda_ttm,
            "roe": _div(ni_ttm, equity_avg), "net_margin": _div(ni_ttm, revenue_ttm) if not financial else None,
            "ebit_margin": _div(ebit_ttm, revenue_ttm) if not financial else None,
            "q_margin": _div(row.get("net_income"), row.get("revenue")) if not financial else None,
            "net_debt": net_debt,
            "net_debt_ebitda": _div(net_debt, ebitda_ttm) if net_debt is not None and ebitda_ttm and ebitda_ttm > 0 else None,
            "dividends_ttm": _ttm(periods, data, index, "dividends_paid"),
            "cfo_ttm": _ttm(periods, data, index, "cfo"), "capex_ttm": _ttm(periods, data, index, "capex"),
        })
        table.append(row)
    return table


def indicators(instrument_id: int, price_cents: int | None = None) -> dict[str, Any] | None:
    """Indicadores atuais: último trimestre publicado + preço do dia (valor de mercado)."""
    profile = rows("SELECT * FROM company_profile WHERE instrument_id = ?", (instrument_id,))
    if not profile:
        return None
    profile = dict(profile[0])
    financial = bool(profile["is_financial"])
    table = quarterly_table(instrument_id, financial)
    if not table:
        return {"profile": profile, "values": {}, "quarters": [], "financial": financial}
    last = table[-1]
    year_ago = table[-5] if len(table) >= 5 else None
    shares = profile["shares_outstanding"] or last.get("shares")
    market_cap = None
    if price_cents and shares:
        market_cap = price_cents / 100 * shares
    elif profile["market_cap_cents"]:
        market_cap = profile["market_cap_cents"] / 100
    net_debt = last.get("net_debt")
    ev = market_cap + net_debt if market_cap is not None and net_debt is not None else None
    fcf = (last["cfo_ttm"] - last["capex_ttm"]) if last.get("cfo_ttm") is not None and last.get("capex_ttm") is not None else None
    values = {
        "pl": _div(market_cap, last["net_income_ttm"]) if last.get("net_income_ttm") and last["net_income_ttm"] > 0 else None,
        "pvp": _div(market_cap, last.get("equity_parent")),
        "ev_ebit": _div(ev, last["ebit_ttm"]) if ev and last.get("ebit_ttm") and last["ebit_ttm"] > 0 else None,
        "ev_ebitda": _div(ev, last["ebitda_ttm"]) if ev and last.get("ebitda_ttm") and last["ebitda_ttm"] > 0 else None,
        "dy": _div(last.get("dividends_ttm"), market_cap),
        "payout": _div(last.get("dividends_ttm"), last["net_income_ttm"]) if last.get("net_income_ttm") and last["net_income_ttm"] > 0 else None,
        "roe": last["roe"], "roa": _div(last.get("net_income_ttm"), last.get("total_assets")),
        "net_margin": last["net_margin"], "ebit_margin": last["ebit_margin"],
        "net_debt_ebitda": last["net_debt_ebitda"], "net_debt_equity": _div(net_debt, last.get("equity_parent")),
        "revenue_growth": _div(last["revenue_ttm"] - year_ago["revenue_ttm"], abs(year_ago["revenue_ttm"]))
        if year_ago and last.get("revenue_ttm") is not None and year_ago.get("revenue_ttm") else None,
        "earnings_growth": _div(last["net_income_ttm"] - year_ago["net_income_ttm"], abs(year_ago["net_income_ttm"]))
        if year_ago and last.get("net_income_ttm") is not None and year_ago.get("net_income_ttm") else None,
        "fcf_yield": _div(fcf, market_cap) if not financial else None,
    }
    if financial:
        for key in FINANCIAL_HIDDEN:
            values[key] = None
    return {
        "profile": profile, "values": values, "quarters": table, "financial": financial,
        "market_cap": market_cap, "last_period": last["period_end"], "last_label": last["label"], "ev": ev,
        "year_ago": year_ago,
    }


# ---------------------------------------------------------------- avisos por regras

def _rule_alerts(ind: dict[str, Any]) -> list[dict[str, Any]]:
    """Checagens simples e explícitas. Servem de piso; o agente de IA entra com leitura mais fina."""
    v, last, year_ago = ind["values"], ind["quarters"][-1], ind.get("year_ago")
    period = ind["last_period"]
    alerts: list[dict[str, Any]] = []

    def add(code, severity, message, metric=None, value=None, threshold=None):
        alerts.append({"code": code, "severity": severity, "message": message, "metric": metric,
                       "value": value, "threshold": threshold, "period_end": period})

    ni_ttm = last.get("net_income_ttm")
    if ni_ttm is not None and ni_ttm < 0:
        add("prejuizo_12m", "critico", "Prejuízo nos últimos 12 meses.", "net_income_ttm", ni_ttm, 0)
    if last.get("net_income") is not None and last["net_income"] < 0 and (ni_ttm is None or ni_ttm >= 0):
        add("prejuizo_trimestre", "atencao", f"Prejuízo no {last['label']}.", "net_income", last["net_income"], 0)
    if v.get("earnings_growth") is not None and v["earnings_growth"] <= -0.2:
        add("lucro_caindo", "atencao", f"Lucro 12M caiu {_p(abs(v['earnings_growth']))} em um ano.", "earnings_growth",
            v["earnings_growth"], -0.2)
    if v.get("revenue_growth") is not None and v["revenue_growth"] <= -0.1 and not ind["financial"]:
        add("receita_caindo", "atencao", f"Receita 12M caiu {_p(abs(v['revenue_growth']))} em um ano.", "revenue_growth",
            v["revenue_growth"], -0.1)
    if v.get("roe") is not None and v["roe"] < 0.08 and (ni_ttm or 0) >= 0:
        add("roe_baixo", "atencao", f"ROE de {_p(v['roe'], 1)}, abaixo de 8%: rende menos que a renda fixa sem risco.", "roe",
            v["roe"], 0.08)
    if year_ago and v.get("roe") is not None and year_ago.get("roe") is not None and v["roe"] - year_ago["roe"] <= -0.05:
        add("roe_caindo", "atencao", f"ROE caiu {_n((year_ago['roe'] - v['roe']) * 100)} p.p. em um ano.", "roe",
            v["roe"], year_ago["roe"])
    if year_ago and v.get("net_margin") is not None and year_ago.get("net_margin") is not None \
            and v["net_margin"] - year_ago["net_margin"] <= -0.03:
        add("margem_caindo", "atencao", f"Margem líquida caiu {_n((year_ago['net_margin'] - v['net_margin']) * 100)} p.p. em um ano.",
            "net_margin", v["net_margin"], year_ago["net_margin"])
    leverage = v.get("net_debt_ebitda")
    if leverage is not None and leverage > 3:
        add("divida_alta", "critico" if leverage > 4 else "atencao", f"Dívida líquida de {_n(leverage)}x o EBITDA.",
            "net_debt_ebitda", leverage, 3)
    if year_ago and leverage is not None and year_ago.get("net_debt_ebitda") is not None \
            and leverage - year_ago["net_debt_ebitda"] >= 1:
        add("divida_subindo", "atencao", f"Alavancagem subiu de {_n(year_ago['net_debt_ebitda'])}x para {_n(leverage)}x em um ano.",
            "net_debt_ebitda", leverage, year_ago["net_debt_ebitda"])
    if v.get("payout") is not None and v["payout"] > 1.0:
        add("payout_acima_lucro", "atencao", f"Pagou {_p(v['payout'])} do lucro em dividendos: acima do que ganhou.",
            "payout", v["payout"], 1.0)
    pl, pvp, roe = v.get("pl"), v.get("pvp"), v.get("roe")
    if pl is not None and pl < 6 and roe is not None and roe >= 0.12 and (v.get("earnings_growth") or 0) > -0.2:
        add("barata_pl", "positivo", f"P/L de {_n(pl)} com ROE de {_p(roe)}: possivelmente barata.", "pl", pl, 6)
    elif pvp is not None and pvp < 1 and roe is not None and roe >= 0.10:
        add("barata_pvp", "positivo", f"Negocia a {_n(pvp, 2)}x o patrimônio com ROE de {_p(roe)}: possivelmente barata.",
            "pvp", pvp, 1)
    if pl is not None and pl > 25:
        add("cara_pl", "atencao", f"P/L de {_n(pl)}: cara pelo lucro atual.", "pl", pl, 25)
    days_old = (date.today() - date.fromisoformat(period)).days
    if days_old > 150:
        add("dados_antigos", "info", f"Último balanço é de {period[8:10]}/{period[5:7]}/{period[:4]}; a CVM ainda não tem o trimestre seguinte.",
            None, days_old, 150)
    return alerts


def refresh_rule_alerts() -> int:
    """Recalcula os avisos das regras: novos entram, os que deixaram de valer são resolvidos."""
    prices = _latest_prices()
    active = 0
    with transaction() as connection:
        produced: set[tuple[int, str, str]] = set()
        for profile in connection.execute("SELECT instrument_id FROM company_profile").fetchall():
            instrument_id = int(profile[0])
            ind = indicators(instrument_id, prices.get(instrument_id))
            if not ind or not ind["quarters"]:
                continue
            for alert in _rule_alerts(ind):
                produced.add((instrument_id, alert["code"], alert["period_end"]))
                connection.execute(
                    "INSERT INTO fundamental_alert(instrument_id, code, severity, message, metric, value, threshold, "
                    "period_end, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'regras') "
                    # 'Visto' pelo usuário continua visto enquanto o período for o mesmo
                    "ON CONFLICT(instrument_id, code, period_end, source) DO UPDATE SET severity = excluded.severity, "
                    "message = excluded.message, value = excluded.value, threshold = excluded.threshold",
                    (instrument_id, alert["code"], alert["severity"], alert["message"], alert["metric"],
                     alert["value"], alert["threshold"], alert["period_end"]),
                )
        for r in connection.execute(
            "SELECT id, instrument_id, code, period_end, resolved_at FROM fundamental_alert WHERE source = 'regras'"
        ).fetchall():
            if (int(r["instrument_id"]), r["code"], r["period_end"]) not in produced:
                connection.execute("DELETE FROM fundamental_alert WHERE id = ?", (r["id"],))
            elif r["resolved_at"] is None:
                active += 1
    return active


def _latest_prices() -> dict[int, int]:
    return {int(r[0]): int(r[1]) for r in rows(
        "SELECT instrument_id, close_cents FROM daily_quote dq WHERE trade_date = "
        "(SELECT MAX(trade_date) FROM daily_quote d2 WHERE d2.instrument_id = dq.instrument_id)"
    )}


def alerts(instrument_id: int | None = None, include_resolved: bool = False) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
    if instrument_id is not None:
        where.append("a.instrument_id = ?")
        params.append(instrument_id)
    if not include_resolved:
        where.append("a.resolved_at IS NULL")
    data = [dict(r) for r in rows(
        "SELECT a.*, i.ticker FROM fundamental_alert a LEFT JOIN instrument i ON i.id = a.instrument_id "
        f"WHERE {' AND '.join(where)} ORDER BY a.created_at DESC", tuple(params),
    )]
    data.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["ticker"] or ""))
    return data


def reports(instrument_id: int | None = None, limit: int = 20, subject_type: str | None = None,
            report_id: int | None = None) -> list[dict[str, Any]]:
    """Relatórios do mais recente para o mais antigo (o histórico fica guardado: um por período)."""
    where, params = ["1 = 1"], []
    if instrument_id is not None:
        where.append("r.instrument_id = ?")
        params.append(instrument_id)
    if subject_type:
        where.append("r.subject_type = ?")
        params.append(subject_type)
    if report_id is not None:
        where.append("r.id = ?")
        params.append(report_id)
    data = [dict(r) for r in rows(
        f"SELECT r.*, i.ticker FROM analysis_report r LEFT JOIN instrument i ON i.id = r.instrument_id "
        f"WHERE {' AND '.join(where)} ORDER BY r.created_at DESC, r.id DESC LIMIT ?", tuple(params) + (limit,),
    )]
    for r in data:
        try:
            r["sources"] = json.loads(r["sources"]) if r["sources"] else []
        except ValueError:
            r["sources"] = [r["sources"]]
    return data


def filings(instrument_id: int, limit: int = 8) -> list[dict[str, Any]]:
    return [dict(r) for r in rows(
        "SELECT * FROM company_filing WHERE instrument_id = ? ORDER BY period_end DESC, doc_type LIMIT ?",
        (instrument_id, limit),
    )]


def agent_metrics(instrument_id: int) -> list[dict[str, Any]]:
    """Métricas gravadas pelo agente (a mais recente de cada)."""
    return [dict(r) for r in rows(
        "SELECT m.* FROM fundamental_metric m WHERE m.instrument_id = ? AND m.source <> 'cvm' AND m.period_end = "
        "(SELECT MAX(period_end) FROM fundamental_metric x WHERE x.instrument_id = m.instrument_id "
        " AND x.metric = m.metric AND x.source = m.source) ORDER BY m.metric", (instrument_id,),
    )]


def portfolio_fundamentals(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Indicadores por empresa e médias da carteira ponderadas pelo valor de cada posição."""
    rows_out = []
    for asset in assets:
        if asset["qty"] <= 0:
            continue
        ind = indicators(asset["iid"], asset["close"])
        if not ind:
            continue
        latest_report = reports(asset["iid"], limit=1)
        rule = [a for a in alerts(asset["iid"])]
        signal = next((a for a in rule if a["code"].startswith(("barata", "cara"))), None)
        rows_out.append({
            "iid": asset["iid"], "ticker": asset["ticker"], "value": asset["value"] or 0, "ind": ind,
            "report": latest_report[0] if latest_report else None, "alerts": rule, "signal": signal,
        })
    total = sum(r["value"] for r in rows_out)
    weighted: dict[str, float | None] = {}
    for key in ("pl", "pvp", "dy", "roe", "net_margin", "earnings_growth"):
        usable = [(r["value"], r["ind"]["values"].get(key)) for r in rows_out if r["ind"]["values"].get(key) is not None]
        weight = sum(w for w, _ in usable)
        if key == "pl":
            # P/L da carteira: valor ÷ lucro proporcional (média harmônica), para não explodir com lucros pequenos
            earnings = sum(w / v for w, v in usable if v > 0)
            weighted[key] = weight / earnings if earnings else None
        else:
            weighted[key] = sum(w * v for w, v in usable) / weight if weight else None
    return {"companies": rows_out, "weighted": weighted, "coverage": _div(total, sum(a["value"] or 0 for a in assets))}


# ---------------------------------------------------------------- contrato com o agente

VERDICTS = {"barata", "justa", "cara"}
SUBJECT_TYPES = ("ativo", "renda_fixa", "previdencia", "carteira")
SEVERITIES = set(SEVERITY_ORDER)


def import_analysis(payload: Any, default_author: str = "agente") -> dict[str, int]:
    """Grava relatórios, métricas e avisos de um agente. Aceita um objeto ou uma lista (ver docs/agente-financeiro.md)."""
    items = payload if isinstance(payload, list) else [payload]
    counts = {"reports": 0, "metrics": 0, "alerts": 0}
    tickers = {r["ticker"].upper(): int(r["id"]) for r in rows("SELECT id, ticker FROM instrument")}
    with transaction() as connection:
        for position, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise FundamentalsError(f"Item {position}: esperado um objeto JSON.")
            ticker = str(item.get("ticker") or "").strip().upper()
            instrument_id = tickers.get(ticker) if ticker else None
            if ticker and instrument_id is None:
                raise FundamentalsError(f"Item {position}: ticker {ticker} não está na carteira.")
            author = str(item.get("author") or default_author)[:40]
            period = str(item.get("period") or "").strip()[:20] or None
            report = item.get("report")
            if report:
                if not isinstance(report, dict) or not str(report.get("title") or "").strip():
                    raise FundamentalsError(f"Item {position}: report precisa de title.")
                verdict = report.get("verdict")
                if verdict is not None and verdict not in VERDICTS:
                    raise FundamentalsError(f"Item {position}: verdict deve ser barata, justa ou cara.")
                fair = report.get("fair_price")
                kind = str(report.get("kind") or "trimestral")[:30]
                subject_type = str(item.get("subject_type") or ("ativo" if instrument_id else "carteira"))
                if subject_type not in SUBJECT_TYPES:
                    raise FundamentalsError(f"Item {position}: subject_type deve ser {', '.join(SUBJECT_TYPES)}.")
                subject = str(item.get("subject") or ticker or "").strip()[:120] or None
                if not instrument_id and subject_type != "carteira" and not subject:
                    raise FundamentalsError(f"Item {position}: relatório sem ticker precisa de subject (ex.: nome do CDB).")
                # mesmo assunto, período, tipo e autor = nova versão do mesmo relatório (IS trata os vazios)
                connection.execute(
                    "DELETE FROM analysis_report WHERE instrument_id IS ? AND subject IS ? AND period IS ? "
                    "AND kind = ? AND author = ?", (instrument_id, subject, period, kind, author),
                )
                connection.execute(
                    "INSERT INTO analysis_report(instrument_id, subject, subject_type, period, kind, title, summary, body_md, "
                    "verdict, score, fair_price_cents, author, model, sources) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (instrument_id, subject, subject_type, period, kind, str(report["title"])[:200],
                     str(report.get("summary") or "")[:2000] or None, str(report.get("body_md") or "")[:200_000] or None,
                     verdict, float(report["score"]) if report.get("score") is not None else None,
                     int(round(float(fair) * 100)) if fair is not None else None, author,
                     str(item.get("model") or "")[:80] or None,
                     json.dumps(report.get("sources") or [], ensure_ascii=False)),
                )
                counts["reports"] += 1
            for metric in item.get("metrics") or []:
                if instrument_id is None:
                    raise FundamentalsError(f"Item {position}: métricas exigem ticker.")
                name = str(metric.get("metric") or "").strip()
                period_end = str(metric.get("period_end") or "").strip()
                period_type = str(metric.get("period_type") or "TTM").upper()
                if not re.fullmatch(r"[a-z0-9_]{2,40}", name):
                    raise FundamentalsError(f"Item {position}: nome de métrica inválido ({name!r}); use snake_case.")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end) or period_type not in {"Q", "TTM", "SNAPSHOT"}:
                    raise FundamentalsError(f"Item {position}: {name} precisa de period_end AAAA-MM-DD e period_type Q/TTM/SNAPSHOT.")
                value = metric.get("value")
                connection.execute(
                    "INSERT INTO fundamental_metric(instrument_id, period_end, period_type, metric, value, unit, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(instrument_id, period_end, period_type, metric, source) "
                    "DO UPDATE SET value = excluded.value, unit = excluded.unit, updated_at = CURRENT_TIMESTAMP",
                    (instrument_id, period_end, period_type, name, float(value) if value is not None else None,
                     str(metric.get("unit") or "")[:20] or None, author),
                )
                counts["metrics"] += 1
            for alert in item.get("alerts") or []:
                severity = str(alert.get("severity") or "atencao")
                if severity not in SEVERITIES:
                    raise FundamentalsError(f"Item {position}: severity deve ser {', '.join(sorted(SEVERITIES))}.")
                code = str(alert.get("code") or "").strip()
                message = str(alert.get("message") or "").strip()
                if not code or not message:
                    raise FundamentalsError(f"Item {position}: aviso precisa de code e message.")
                connection.execute(
                    "INSERT INTO fundamental_alert(instrument_id, code, severity, message, metric, value, threshold, "
                    "period_end, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(instrument_id, code, period_end, source) DO UPDATE SET severity = excluded.severity, "
                    "message = excluded.message, value = excluded.value, threshold = excluded.threshold, resolved_at = NULL",
                    (instrument_id, code[:60], severity, message[:500], alert.get("metric"), alert.get("value"),
                     alert.get("threshold"), str(alert.get("period_end") or period or "")[:20] or None, author),
                )
                counts["alerts"] += 1
    return counts


def resolve_alert(alert_id: int) -> None:
    with transaction() as connection:
        connection.execute("UPDATE fundamental_alert SET resolved_at = CURRENT_TIMESTAMP WHERE id = ?", (int(alert_id),))


def agent_context(ticker: str) -> dict[str, Any]:
    """Tudo o que um agente precisa para analisar um ativo, num JSON só."""
    found = rows("SELECT id, ticker, name, asset_class FROM instrument WHERE ticker = ?", (ticker.upper(),))
    if not found:
        raise FundamentalsError(f"{ticker} não está cadastrado.")
    instrument = dict(found[0])
    iid = int(instrument["id"])
    price = _latest_prices().get(iid)
    ind = indicators(iid, price)
    return {
        "ticker": instrument["ticker"], "name": instrument["name"], "asset_class": instrument["asset_class"],
        "price": price / 100 if price else None,
        "profile": ind["profile"] if ind else None,
        "indicators": ind["values"] if ind else None,
        "market_cap": ind["market_cap"] if ind else None,
        "quarters": [{k: v for k, v in q.items()} for q in ind["quarters"]] if ind else [],
        "filings": filings(iid, 12), "alerts": alerts(iid), "reports": reports(iid, 5),
        "agent_metrics": agent_metrics(iid),
        "region": rows("SELECT COALESCE(region, '') FROM instrument WHERE id = ?", (iid,))[0][0] or None,
        "units": "valores monetários em reais; percentuais como fração (0.15 = 15%)",
        "see_also": "financas carteira contexto (metas e carteira inteira); financas analise mostrar ID (relatório completo)",
    }
