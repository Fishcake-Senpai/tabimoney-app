"""Análise de longo prazo: o perfil do investidor (horizonte e objetivo) que as análises perguntam antes de começar.

Spec: docs/superpowers/specs/2026-09-30-analise-longo-prazo.md.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app import cli
from app.agente import operacoes as op
from app.services import household, investor_profile

from .conftest import avisos, csrf


def _cli(capsys, *args: str) -> dict:
    capsys.readouterr()
    cli.main(list(args))
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- perfil do investidor

def test_sem_perfil_a_ia_sabe_que_precisa_perguntar():
    perfil = op.perfil_investidor()
    assert perfil["configurado"] is False and perfil["horizonte"] is None
    assert "10-20" in perfil["opcoes"]["horizonte"] and "renda" in perfil["opcoes"]["objetivo"]
    assert op.carteira_contexto()["perfil"]["configurado"] is False


def test_grava_e_volta_no_contexto_da_carteira():
    op.perfil_definir("mais-de-20", "crescimento")
    perfil = op.carteira_contexto()["perfil"]
    assert perfil["configurado"] is True
    assert perfil["horizonte_texto"] == "mais de 20 anos" and perfil["objetivo_texto"] == "crescimento do patrimônio"
    assert perfil["atualizado_em"] == date.today().isoformat() and perfil["vencido"] is False


@pytest.mark.parametrize(("horizonte", "objetivo"), [("15", "renda"), ("10-20", "especular")])
def test_valores_fora_das_opcoes_sao_recusados(horizonte, objetivo):
    with pytest.raises(ValueError):
        op.perfil_definir(horizonte, objetivo)


def test_perfil_com_mais_de_um_ano_esta_vencido():
    investor_profile.save("5-10", "renda", today=date(2025, 1, 10))
    assert investor_profile.load(today=date(2026, 1, 9))["stale"] is False
    assert investor_profile.load(today=date(2026, 1, 11))["stale"] is True


def test_titular_usa_o_da_casa_ate_ter_o_proprio():
    ana = household.add_member("Ana")["id"]
    op.perfil_definir("10-20", "os-dois")
    assert op.perfil_investidor(ana)["horizonte"] == "10-20"
    assert op.perfil_investidor(ana)["de"] == "casa (titular sem perfil próprio)"
    op.perfil_definir("5-10", "renda", member=ana)
    assert op.perfil_investidor(ana)["horizonte"] == "5-10" and op.perfil_investidor(ana)["de"] == "titular"
    assert op.perfil_investidor()["horizonte"] == "10-20"
    investor_profile.clear(ana)
    assert op.perfil_investidor(ana)["horizonte"] == "10-20"


def test_cli_mostra_e_define(capsys):
    assert _cli(capsys, "perfil", "definir", "10-20", "crescimento")["horizonte"] == "10-20"
    assert _cli(capsys, "perfil", "mostrar")["objetivo"] == "crescimento"


def test_tela_de_metas_mostra_e_grava_o_perfil(client):
    assert "Definir horizonte" in client.get("/metas").text
    page = client.post("/metas/perfil", data={"csrf_token": csrf(client), "horizon": "mais-de-20", "goal": "renda"},
                       follow_redirects=True)
    assert ("success", "Horizonte e objetivo salvos.") in avisos(page.text)
    assert "Horizonte: mais de 20 anos · renda passiva" in page.text


def test_tela_de_metas_recusa_horizonte_invalido(client):
    page = client.post("/metas/perfil", data={"csrf_token": csrf(client), "horizon": "2", "goal": "renda"},
                       follow_redirects=True)
    assert avisos(page.text)[0][0] == "error"
    assert op.perfil_investidor()["configurado"] is False


# ---------------------------------------------------------------- série anual (dez anos de DFP)

def _instrumento(ticker: str = "TEST3", financeira: bool = False) -> int:
    from app import db
    with db.transaction() as con:
        iid = con.execute("INSERT INTO instrument(ticker, name, asset_class) VALUES (?, ?, 'Ação')",
                          (ticker, "Teste S.A.")).lastrowid
        con.execute("INSERT INTO company_profile(instrument_id, company_name, is_financial) VALUES (?, ?, ?)",
                    (iid, "Teste S.A.", int(financeira)))
    return int(iid)


def _gravar(iid: int, period_end: str, period_type: str, source: str, **valores: float) -> None:
    from app import db
    with db.transaction() as con:
        con.executemany(
            "INSERT INTO fundamental_metric(instrument_id, period_end, period_type, metric, value, source) "
            "VALUES (?, ?, ?, ?, ?, ?)", [(iid, period_end, period_type, k, v, source) for k, v in valores.items()])


def _ano(iid: int, ano: int, receita: float, lucro: float, patrimonio: float = 1000.0, **extra: float) -> None:
    from app.services import fundamentals
    _gravar(iid, f"{ano}-12-31", "TTM", fundamentals.ANNUAL_SOURCE, revenue=receita, net_income=lucro,
            dividends_paid=max(lucro, 0) / 2, **{k: v for k, v in extra.items() if k in ("ebit", "da")})
    _gravar(iid, f"{ano}-12-31", "SNAPSHOT", fundamentals.ANNUAL_SOURCE, equity_parent=patrimonio, shares=100.0,
            **{k: v for k, v in extra.items() if k in ("debt", "cash")})


def test_serie_anual_com_cagr_e_prejuizo():
    from app.services import fundamentals
    iid = _instrumento()
    for i, ano in enumerate(range(2015, 2026)):
        _ano(iid, ano, receita=1000 * 1.1 ** i, lucro=-50 if ano == 2018 else 100 * 1.1 ** i,
             ebit=200 * 1.1 ** i, da=20, debt=300, cash=100)
    tabela = fundamentals.annual_table(iid, False)
    assert [r["ano"] for r in tabela] == list(range(2015, 2026))
    ultimo = tabela[-1]
    assert ultimo["margem_liquida"] == pytest.approx(0.1)
    assert ultimo["divida_liquida"] == 200 and ultimo["divida_liquida_ebitda"] == pytest.approx(200 / (200 * 1.1 ** 10 + 20))
    assert ultimo["proventos_por_acao"] == pytest.approx(100 * 1.1 ** 10 / 2 / 100)
    resumo = fundamentals.annual_summary(tabela)
    assert resumo["cagr_receita_5a"] == pytest.approx(0.1) and resumo["cagr_receita_10a"] == pytest.approx(0.1)
    assert resumo["cagr_lucro_10a"] == pytest.approx(0.1)
    assert resumo["anos_com_prejuizo"] == [2018] and resumo["anos_com_lucro"] == 10
    assert resumo["lucro_em_todos_os_ultimos_5_anos"] is True and resumo["anos_pagando_proventos_5a"] == 5


def test_com_menos_de_5_anos_nao_ha_media_de_5_anos():
    from app.services import fundamentals
    iid = _instrumento()
    for ano in (2024, 2025):
        _ano(iid, ano, 1000, 100)
    resumo = fundamentals.annual_summary(fundamentals.annual_table(iid, False))
    assert resumo["anos_disponiveis"] == 2 and resumo["roe_medio_5a"] is None and resumo["cagr_lucro_5a"] is None
    assert resumo["lucro_em_todos_os_ultimos_5_anos"] is False


def test_ano_sem_dfp_sai_da_soma_dos_trimestres():
    from app.services import fundamentals
    iid = _instrumento()
    for mes in ("03-31", "06-30", "09-30", "12-31"):
        _gravar(iid, f"2025-{mes}", "Q", "cvm", revenue=250.0, net_income=25.0)
        _gravar(iid, f"2025-{mes}", "SNAPSHOT", "cvm", equity_parent=500.0)
    _gravar(iid, "2026-03-31", "Q", "cvm", revenue=300.0, net_income=30.0)  # ano incompleto fica de fora
    tabela = fundamentals.annual_table(iid, False)
    assert [(r["ano"], r["receita"], r["lucro"]) for r in tabela] == [(2025, 1000.0, 100.0)]


def test_banco_sem_ebitda_nem_divida_liquida():
    from app.services import fundamentals
    iid = _instrumento("BANK3", financeira=True)
    _ano(iid, 2025, 5000, 900, patrimonio=6000, ebit=1000, da=10, debt=9000, cash=10)
    r = fundamentals.annual_table(iid, True)[-1]
    assert r["ebit"] is None and r["divida_liquida"] is None and r["margem_liquida"] is None
    assert r["roe"] == pytest.approx(0.15)


def test_contexto_do_agente_traz_os_anos_e_nao_mistura_com_metricas_do_agente():
    from app.services import fundamentals
    iid = _instrumento()
    _ano(iid, 2025, 1000, 100)
    contexto = op.fundamentos_contexto("TEST3")
    assert contexto["anos"]["serie"][0]["ano"] == 2025 and "resumo" in contexto["anos"]
    assert fundamentals.agent_metrics(iid) == []


def test_cvm_le_dfp_antiga_so_na_serie_anual(monkeypatch):
    """Anos só anuais pedem só a DFP e não entram na série trimestral (sem ITR não há trimestre)."""
    from app.providers import cvm

    pedidos = []

    def carregar(kind, year, cnpjs, filings, statements, shares):
        pedidos.append((kind, year))
        if kind != "DFP":
            return
        end = f"{year}-12-31"
        dre = statements.setdefault(("1", end, "DRE"), cvm._Statement())
        dre.add("3.01", "Receita de Venda de Bens e/ou Serviços", f"{year}-01-01", end, 1000.0 + year)
        dre.add("3.11", "Lucro/Prejuízo Consolidado do Período", f"{year}-01-01", end, 100.0)
        bpp = statements.setdefault(("1", end, "BPP"), cvm._Statement())
        bpp.add("2.03", "Patrimônio Líquido Consolidado", "", end, 800.0)

    monkeypatch.setattr(cvm, "_load_year", carregar)
    trimestres, _, anuais = cvm.statements_by_company({"1"}, [2025], [2016, 2017])
    assert ("ITR", 2016) not in pedidos and ("ITR", 2025) in pedidos and ("DFP", 2016) in pedidos
    assert [a.period_end for a in anuais["1"]] == ["2016-12-31", "2017-12-31", "2025-12-31"]
    assert anuais["1"][0].values["revenue"] == 3016.0 and anuais["1"][0].values["net_income"] == 100.0
    assert anuais["1"][0].values["equity_parent"] == 800.0
    assert all(q.period_end.startswith("2025") for q in trimestres["1"])


# ---------------------------------------------------------------- tela do ativo: a tese em destaque

def _rel(id_: int, kind: str, score: float | None, criado: str) -> dict:
    return {"id": id_, "kind": kind, "score": score, "created_at": criado, "title": f"r{id_}"}


def test_tese_fica_em_destaque_e_o_acompanhamento_mais_novo_vem_junto():
    from app.services import fundamentals
    rel = [_rel(3, "trimestral", 7.0, "2026-09-01 10:00:00"), _rel(2, "tese", 9.1, "2026-06-01 10:00:00"),
           _rel(1, "trimestral", 6.0, "2026-03-01 10:00:00")]
    v = fundamentals.reports_view(rel, today=date(2026, 9, 30))
    assert v["lead"]["id"] == 2 and v["follow"]["id"] == 3 and v["current"]["id"] == 3
    assert v["role"] == "complementar" and v["stale"] is False
    assert [r["id"] for r in v["history"]] == [3, 1]


def test_sem_tese_vale_o_mais_recente_sem_papel():
    from app.services import fundamentals
    v = fundamentals.reports_view([_rel(5, "trimestral", 8.5, "2026-09-01 10:00:00")])
    assert v["lead"]["id"] == 5 and v["thesis"] is None and v["role"] is None and v["history"] == []
    assert fundamentals.reports_view([])["lead"] is None


@pytest.mark.parametrize(("score", "papel"), [(9.1, "núcleo"), (8.0, "núcleo"), (5.0, "complementar"),
                                              (4.9, "evitar novos aportes"), (None, None)])
def test_papel_pela_nota(score, papel):
    from app.services import fundamentals
    assert fundamentals.thesis_role(score) == papel


def test_tese_com_mais_de_um_ano_esta_vencida():
    from app.services import fundamentals
    v = fundamentals.reports_view([_rel(1, "tese", 9.0, "2025-09-01 10:00:00")], today=date(2026, 9, 30))
    assert v["stale"] is True and v["role"] == "núcleo" and v["follow"] is None


def test_pagina_do_ativo_na_demo_mostra_tese_e_acompanhamento(client):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    visao = client.get("/ativo/WEGE3").text
    assert "Tese de longo prazo" in visao and "Núcleo" in visao and "Acompanhamento" in visao
    analises = client.get("/ativo/WEGE3?aba=analises").text
    assert "Tese de longo prazo" in analises
    assert "núcleo para 10 a 20 anos" in analises and "tese de pé" in analises  # a tese e o acompanhamento
    sem_tese = client.get("/ativo/EGIE3?aba=analises").text
    assert "Análise mais recente" in sem_tese
