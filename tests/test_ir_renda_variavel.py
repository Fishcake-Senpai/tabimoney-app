"""Apuração do IR na bolsa (app/services/ir/renda_variavel.py): o exemplo da spec (§A.5) e as regras de borda.

Cada regra vem das Perguntas e Respostas IRPF 2026 da Receita (perguntas 704 a 745), citadas no módulo.
"""
from __future__ import annotations

from datetime import date
from itertools import count

import pytest

from app import db
from app.services.ir import renda_variavel as rv

HOJE = date(2026, 10, 19)
_ids = count(1)


def conta(nome: str, member: int | None = None) -> int:
    with db.transaction() as con:
        cur = con.execute(
            "INSERT INTO financial_account(institution, account_name, account_type, provider, external_key, member_id) "
            "VALUES (?, ?, 'INVESTMENT', 'b3', ?, ?)", (nome, nome, f"teste:{nome}", member))
        return int(cur.lastrowid)


def ativo(ticker: str, classe: str = "Ação") -> int:
    with db.transaction() as con:
        con.execute("INSERT OR IGNORE INTO instrument(ticker, name, asset_class) VALUES (?, ?, ?)", (ticker, ticker, classe))
        return int(con.execute("SELECT id FROM instrument WHERE ticker = ?", (ticker,)).fetchone()[0])


def evento(conta_id: int, ticker: str, dia: str, tipo: str, qtd: float, valor: float | None = None,
           preco: float | None = None, fonte: str = "b3", classe: str = "Ação") -> int:
    iid = ativo(ticker, classe)
    q = int(round(qtd * 1_000_000))
    with db.transaction() as con:
        cur = con.execute(
            "INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, event_type, "
            "quantity_micros, amount_cents, unit_price_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conta_id, iid, fonte, f"ev{next(_ids)}", dia, tipo, -q if tipo == "SELL" else q,
             None if valor is None else int(round(valor * 100)), None if preco is None else int(round(preco * 100))))
        return int(cur.lastrowid)


def mes(resultado: dict, m: str) -> dict:
    return next(x for x in resultado["meses"] if x["mes"] == m)


@pytest.fixture
def ana():
    """O exemplo da spec §A.5: duas corretoras, ações isentas, FII, ETF e day trade em 2026."""
    xp, btg = conta("XP"), conta("BTG")
    evento(xp, "PETR4", "2025-06-10", "BUY", 2000, 54000)
    evento(xp, "HGLG11", "2026-01-05", "BUY", 20, 3400, classe="FII")
    evento(xp, "BOVA11", "2026-01-05", "BUY", 100, 11950, classe="ETF")
    evento(xp, "ITSA4", "2026-01-12", "BUY", 100, 1000.30)
    evento(btg, "ITSA4", "2026-01-15", "BUY", 100, 1200.30)
    evento(xp, "ITSA4", "2026-02-10", "SELL", 100, 1299.73)
    evento(btg, "ITSA4", "2026-02-10", "SELL", 50, 649.87)
    evento(btg, "ITSA4", "2026-03-10", "SELL", 50, 449.90)
    evento(xp, "HGLG11", "2026-03-11", "SELL", 10, 1600, classe="FII")
    evento(xp, "PETR4", "2026-04-15", "SELL", 2000, 59997)
    evento(xp, "BOVA11", "2026-05-20", "SELL", 100, 12000, classe="ETF")
    evento(xp, "HGLG11", "2026-06-15", "SELL", 10, 2000, classe="FII")
    evento(xp, "WEGE3", "2026-07-08", "BUY", 100, 4000.25)
    evento(xp, "WEGE3", "2026-07-08", "SELL", 100, 4099.75)
    return rv.apurar(1, 2026, HOJE)


def test_preco_medio_junta_as_corretoras_e_isenta_ate_20_mil(ana):
    fev = mes(ana, "2026-02")
    custos = [v["custo"] for v in fev["vendas"]]
    assert custos == [110030, 55015]            # PM consolidado 11,003 (por conta seria 10,003 e 12,003)
    assert fev["isento"] == 29915 and fev["darf"] == 0
    assert ana["isentos_linha_20"] == 29915


def test_prejuizo_em_mes_isento_compensa_depois(ana):
    mar = mes(ana, "2026-03")
    assert mar["resultado_acoes"] == -10025 and mar["isento"] == 0
    assert mar["prejuizo_fim"]["comum"] == 10025 and mar["prejuizo_fim"]["fii"] == 10000
    abr = mes(ana, "2026-04")
    assert abr["compensado"]["comum"] == 10025 and abr["base"]["comum"] == 589675
    assert abr["imposto"]["comum"] == 88451
    assert abr["irrf"]["comum"] == 300           # 0,005% de 60 mil
    assert abr["darf"] == 88151 and abr["vencimento"] == "2026-05-29"


def test_etf_sem_isencao_e_darf_abaixo_de_10_acumula(ana):
    mai = mes(ana, "2026-05")
    assert mai["imposto"]["comum"] == 750 and mai["irrf"]["comum"] == 0   # 0,60 de IRRF: abaixo de R$ 1, não retém
    assert mai["darf"] == 0 and mai["acumulado"] == 750
    jun = mes(ana, "2026-06")
    assert jun["compensado"]["fii"] == 10000 and jun["imposto"]["fii"] == 4000
    assert jun["darf"] == 4750


def test_day_trade_separado_com_irrf_de_1(ana):
    jul = mes(ana, "2026-07")
    assert jul["resultado"]["day_trade"] == 9950 and jul["imposto"]["day_trade"] == 1990
    assert jul["irrf"]["day_trade"] == 100 and jul["darf"] == 1890
    assert all(v["day_trade"] for v in jul["vendas"])


def test_bens_e_direitos_pelo_custo(ana):
    bens = {b["ticker"]: b for b in ana["bens"]}
    assert bens["PETR4"]["anterior"] == 5400000 and bens["PETR4"]["atual"] == 0
    assert "ITSA4" in bens and bens["ITSA4"]["atual"] == 0
    assert ana["obriga_declarar"] is True


def test_isencao_exatamente_em_20_mil():
    xp = conta("XP")
    evento(xp, "VALE3", "2026-01-05", "BUY", 1000, 15000)
    evento(xp, "VALE3", "2026-02-05", "SELL", 500, 20000)       # vendas = 20.000,00: isento
    evento(xp, "VALE3", "2026-03-05", "SELL", 500, 20000.01)    # 20.000,01: tributável
    r = rv.apurar(1, 2026, HOJE)
    assert mes(r, "2026-02")["isento"] == 1250000 and mes(r, "2026-02")["darf"] == 0
    assert mes(r, "2026-03")["isento"] == 0 and mes(r, "2026-03")["base"]["comum"] == 1250001


def test_day_trade_conta_no_limite_de_20_mil():
    xp = conta("XP")
    evento(xp, "VALE3", "2026-01-05", "BUY", 100, 1000)
    evento(xp, "BBAS3", "2026-02-05", "BUY", 1000, 15000)
    evento(xp, "BBAS3", "2026-02-05", "SELL", 1000, 15500)      # day trade de 15.500 em vendas
    evento(xp, "VALE3", "2026-02-10", "SELL", 100, 5000)        # comum: 15.500 + 5.000 > 20 mil
    r = rv.apurar(1, 2026, HOJE)
    fev = mes(r, "2026-02")
    assert fev["vendas_acoes"] == 2050000 and fev["isento"] == 0
    assert fev["base"]["comum"] == 400000 and fev["base"]["day_trade"] == 50000


def test_sobra_do_day_trade_vira_operacao_comum():
    xp = conta("XP")
    evento(xp, "ITSA4", "2026-01-05", "BUY", 100, 1000)
    evento(xp, "ITSA4", "2026-01-20", "BUY", 50, 600)
    evento(xp, "ITSA4", "2026-01-20", "SELL", 120, 1560)        # 50 em day trade, 70 pelo preço médio
    r = rv.apurar(1, 2026, HOJE)
    vendas = mes(r, "2026-01")["vendas"]
    dt = next(v for v in vendas if v["day_trade"])
    comum = next(v for v in vendas if not v["day_trade"])
    assert dt["quantidade"] == 50_000_000 and dt["custo"] == 60000 and dt["valor"] == 65000
    assert comum["quantidade"] == 70_000_000 and comum["custo"] == 70000


def test_desdobro_grupamento_e_bonificacao_com_custo():
    xp = conta("XP")
    evento(xp, "ITSA4", "2026-01-05", "BUY", 100, 1000)
    evento(xp, "ITSA4", "2026-02-01", "SPLIT", 100)                 # desdobro 1:2, custo total igual
    bonus = evento(xp, "ITSA4", "2026-03-01", "BONUS", 20)          # sem custo: pendência
    r = rv.apurar(1, 2026, HOJE)
    assert any(p["tipo"] == "bonificacao" for p in r["pendencias"])
    rv.informar(1, "custo_bonificacao", 500, ref_id=bonus)          # R$ 5,00 por ação
    evento(xp, "ITSA4", "2026-04-01", "SELL", 220, 2200)
    r = rv.apurar(1, 2026, HOJE)
    abr = mes(r, "2026-04")
    assert abr["vendas"][0]["custo"] == 110000                      # 1.000 + 20 × 5
    assert not any(p["tipo"] == "bonificacao" for p in r["pendencias"])


def test_mesma_venda_da_b3_e_da_pluggy_conta_uma_vez():
    xp = conta("XP")
    evento(xp, "ITSA4", "2026-01-05", "BUY", 100, 1000, fonte="b3")
    evento(xp, "ITSA4", "2026-01-05", "BUY", 100, 1000, fonte="pluggy")
    evento(xp, "ITSA4", "2026-02-05", "SELL", 100, 25000, fonte="b3")
    evento(xp, "ITSA4", "2026-02-05", "SELL", 100, 25000, fonte="pluggy")
    r = rv.apurar(1, 2026, HOJE)
    assert len(mes(r, "2026-02")["vendas"]) == 1
    assert mes(r, "2026-02")["base"]["comum"] == 2400000


def test_titulares_apuram_separado():
    from app.services import household

    marina = household.add_member("Marina")["id"]
    a, b = conta("XP Lucas"), conta("XP Marina", marina)
    evento(a, "VALE3", "2026-01-05", "BUY", 1000, 10000)
    evento(b, "VALE3", "2026-01-05", "BUY", 1000, 10000)
    evento(a, "VALE3", "2026-02-05", "SELL", 1000, 15000)
    evento(b, "VALE3", "2026-02-05", "SELL", 1000, 15000)
    assert mes(rv.apurar(1, 2026, HOJE), "2026-02")["isento"] == 500000      # cada um no seu limite
    assert mes(rv.apurar(marina, 2026, HOJE), "2026-02")["isento"] == 500000


def test_prejuizo_informado_de_antes_do_historico_e_irrf_da_nota():
    xp = conta("XP")
    evento(xp, "VALE3", "2026-01-05", "BUY", 1000, 20000)
    evento(xp, "VALE3", "2026-02-05", "SELL", 1000, 30000)
    rv.informar(1, "prejuizo_anterior", 300000, period="2026", grupo="comum")
    rv.informar(1, "irrf", 150, period="2026-02", grupo="comum")
    fev = mes(rv.apurar(1, 2026, HOJE), "2026-02")
    assert fev["compensado"]["comum"] == 300000 and fev["base"]["comum"] == 700000
    assert fev["irrf"]["comum"] == 150 and fev["darf"] == 105000 - 150


def test_venda_sem_custo_e_ticker_11_sem_classe_viram_pendencia():
    xp = conta("XP")
    evento(xp, "XPTO11", "2026-01-05", "BUY", 10, 1000, classe="FII/ETF/Unit")
    evento(xp, "ABCD3", "2026-02-05", "SELL", 10, 100)
    r = rv.apurar(1, 2026, HOJE)
    tipos = {p["tipo"] for p in r["pendencias"]}
    assert {"classe", "estoque_negativo"} <= tipos and r["bloqueado"]
    rv.definir_classe("XPTO11", "fii")
    assert "classe" not in {p["tipo"] for p in rv.apurar(1, 2026, HOJE)["pendencias"]}


def test_classe_sugerida():
    assert rv.classe_sugerida("PETR4", "Ação") == "acao"
    assert rv.classe_sugerida("TAEE11", "Ação") == "unit"
    assert rv.classe_sugerida("TAEE11", "FII/ETF/Unit") == "unit"
    assert rv.classe_sugerida("BOVA11", "FII/ETF/Unit") == "etf"
    assert rv.classe_sugerida("XPTO11", "FII/ETF/Unit") is None
    assert rv.classe_sugerida("HGLG11", "FII") == "fii"
    assert rv.classe_sugerida("AAPL34", "Ação") == "bdr"
    assert rv.classe_sugerida("IMAB11", "ETF") == "etf_rf"


def test_ticker_11_que_a_corretora_chama_de_acao_vira_pendencia():
    # Regressão: a Pluggy marca tudo como "Ação", inclusive ETF e FII. O ticker 11 fora das listas virava unit sem
    # perguntar e ganhava a isenção de R$ 20 mil (AUVP11, um ETF, apareceu como unit em 03.01).
    assert rv.classe_sugerida("XPTO11", "Ação") is None
    assert rv.classe_sugerida("AUVP11", "Ação") == "etf"
    xp = conta("XP")
    evento(xp, "XPTO11", "2026-02-10", "BUY", 10, 1000)
    r = rv.apurar(1, 2026, HOJE)
    assert r["bloqueado"] and [p["tipo"] for p in r["pendencias"]] == ["classe"]


def test_vencimento_no_ultimo_dia_util():
    assert rv.vencimento("2026-04") == date(2026, 5, 29)    # 30 e 31 de maio caem no fim de semana
    assert rv.vencimento("2026-12") == date(2027, 1, 29)


def test_provento_sem_tipo_aparece_na_declaracao_com_aviso():
    # Regressão: a Pluggy manda dividendo e JCP como INTEREST, sem descrição. Eles caíam em "outros" e a declaração
    # só montava fichas de dividendos e de JCP, então sumiam sem aviso nenhum.
    from app.services.ir import declaracao
    xp = conta("XP")
    evento(xp, "BBAS3", "2025-03-10", "BUY", 100, 2500)
    evento(xp, "BBAS3", "2025-06-10", "INTEREST", 0, 87.45)
    evento(xp, "BBAS3", "2025-09-10", "DIVIDEND", 0, 12.00)
    assert {p["ticker"]: p["outros"] for p in rv.apurar(1, 2025, HOJE)["proventos"]} == {"BBAS3": 8745}
    secoes = {s["id"]: s for s in declaracao.montar(1, 2025, HOJE)["secoes"]}
    sem_tipo = [i for i in secoes["isentos"]["itens"] if "BBAS3" in i["titulo"] and "sem tipo" in i["titulo"]]
    assert len(sem_tipo) == 1 and "87,45" in [c["valor"] for c in sem_tipo[0]["campos"]]
    assert "JCP" in sem_tipo[0]["aviso"] and "informe" in sem_tipo[0]["aviso"]
    assert any("dividendos" in i["titulo"] and "BBAS3" in i["titulo"] for i in secoes["isentos"]["itens"])


def posicao(conta_id: int, ticker: str, dia: str, qtd: float, classe: str = "Ação") -> None:
    iid = ativo(ticker, classe)
    with db.transaction() as con:
        con.execute("INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
                    "VALUES (?, ?, 'pluggy', ?, ?)", (conta_id, iid, dia, int(round(qtd * 1_000_000))))


def test_custodia_maior_que_o_historico_vira_pendencia():
    # Regressão: a Pluggy manda só uns 12 meses de operações. Bens e Direitos saía só com o que o histórico explicava
    # (20 IVVB11 em vez de 148) e o papel sem compra no histórico sumia, sem aviso nenhum.
    xp = conta("XP")
    evento(xp, "IVVB11", "2025-11-10", "BUY", 16, 6400, classe="ETF")
    posicao(xp, "IVVB11", "2026-10-20", 148, classe="ETF")
    posicao(xp, "TAEE11", "2026-10-20", 304)
    r = rv.apurar(1, 2026, HOJE)
    pend = {p["ticker"]: p for p in r["pendencias"] if p["tipo"] == "posicao_sem_historico"}
    assert set(pend) == {"IVVB11", "TAEE11"} and not r["bloqueado"]
    assert "148" in pend["IVVB11"]["texto"] and "16" in pend["IVVB11"]["texto"]
    assert next(b for b in r["bens"] if b["ticker"] == "IVVB11")["quantidade_sem_historico"] == 132_000_000
    evento(xp, "IVVB11", "2025-10-01", "OPENING", 132, 40000, classe="ETF")    # posição inicial com preço médio
    r = rv.apurar(1, 2026, HOJE)
    assert [p["ticker"] for p in r["pendencias"] if p["tipo"] == "posicao_sem_historico"] == ["TAEE11"]
    assert next(b for b in r["bens"] if b["ticker"] == "IVVB11")["quantidade_sem_historico"] == 0
