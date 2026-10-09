"""Demonstração: cobre todas as telas, nunca toca nos dados nem no cofre do usuário e se recria sozinha.

Se este teste falhar porque uma página aparece vazia na demo, acrescente exemplos em app/demo.py.
"""
from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import quote

import pytest
from fastapi.routing import APIRoute

from app import cli, db, demo, security
from app.main import app
from app.services import analytics, household

from .conftest import avisos, csrf

ROTAS_GET = sorted(
    r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
    and not r.path.startswith("/csv/") and r.path not in {"/favicon.ico", "/importacoes"}
    and not r.path.startswith("/atualizacao")  # progresso da atualização: página à parte, sem dado nenhum
)
# Textos que as telas mostram quando não há dado. Na demo, nenhum pode aparecer.
VAZIOS = [
    "Nenhum dado ainda", "Nenhuma meta ainda", "Nenhuma análise ainda", "Nada importado ainda", "Nenhum provento",
    "Sem posições", "Nenhum lançamento", "O agente ainda não analisou", "Nenhum relatório", "Defina as metas abaixo",
    "Sem gastos nos últimos meses", "Sem despesas no período", "Sem despesas neste mês", "Sem operações",
    "Nenhuma conta rendendo CDI", "Nenhum par encontrado", "Você ainda não criou nenhuma categoria",
    "Poucos dados para tirar conclusões",
]


def _contagens() -> dict[str, int]:
    tabelas = ("financial_account", "cash_transaction", "investment_event", "household_member", "budget", "app_setting")
    return {t: db.rows(f"SELECT COUNT(*) FROM {t}")[0][0] for t in tabelas}


@pytest.fixture
def na_demo(client):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    return client


def _conteudo(html: str) -> str:
    return html.split('id="conteudo"', 1)[-1]


# ---------------------------------------------------------------- isolamento

def test_entrar_na_demo_nao_toca_na_base_real(client, dados_exemplo):
    antes = _contagens()
    token = csrf(client)
    r = client.post("/demo/entrar", data={"csrf_token": token})
    assert "Olá, Lucas!" in r.text and "Demonstração · dados fictícios" in r.text
    uber = next(t for t in analytics.cash_transactions() if t["description"] == "Uber")
    with demo.active():
        petz = next(t for t in analytics.cash_transactions() if t["description"] == "Petz Pet Shop")
    client.post("/contas/categoria", data={"csrf_token": token, "transaction_id": petz["id"], "category": "Lazer"})
    client.post("/orcamento", data={"csrf_token": token, "name": "Meta da demo", "limit": "100", "categories": ["Lazer"]})
    assert _contagens() == antes
    assert next(t for t in analytics.cash_transactions() if t["id"] == uber["id"])["category"] == "Transporte"
    assert demo.path().exists() and demo.path() != db.database_path()


def test_sair_da_demo_volta_para_os_dados_reais(na_demo, dados_exemplo):
    pagina = na_demo.post("/demo/sair", data={"csrf_token": csrf(na_demo)}).text
    assert "Demonstração · dados fictícios" not in pagina and "Olá, Lucas" not in pagina
    assert "Nubank ••••0001" in na_demo.get("/contas").text


def test_demo_nao_usa_o_cofre_do_sistema(na_demo, cofre):
    pagina = na_demo.get("/configuracoes").text
    assert pagina.count("Configurada") >= 4  # as duas conexões e a brapi da demo
    na_demo.post("/configuracoes", data={"csrf_token": csrf(na_demo), "brapi_token": "token-da-demo"})
    assert cofre.dados == {}
    assert security.get_secret("brapi_token") is None


def test_outra_aba_fora_da_demo_continua_nos_dados_reais(na_demo, dados_exemplo):
    from fastapi.testclient import TestClient

    from app import main

    with TestClient(main.app, base_url=f"http://127.0.0.1:{main.PORT}", client=("127.0.0.1", 50001)) as outra:
        assert "Nubank ••••0001" in outra.get("/contas").text
    assert "Nubank ••••4821" in na_demo.get("/contas").text


@pytest.mark.parametrize("rota, texto", [
    ("/sincronizar/pluggy", "sincronizar o Open Finance"), ("/sincronizar/cotacoes", "atualizar o mercado"),
    ("/fundamentos/atualizar", "atualizar os balanços da CVM"), ("/atualizacao/verificar", "verificar versão nova"),
])
def test_na_demo_o_que_busca_dados_de_fora_fica_desligado(na_demo, rota, texto):
    execucoes = len(db.rows("SELECT id FROM sync_run"))
    r = na_demo.post(rota, data={"csrf_token": csrf(na_demo)})
    assert any(tipo == "warning" and texto in msg for tipo, msg in avisos(r.text))
    with demo.active():
        assert not db.rows("SELECT 1 FROM sync_run WHERE status = 'failed'")
    assert len(db.rows("SELECT id FROM sync_run")) == execucoes


def test_na_demo_backup_e_restauracao_ficam_desligados(na_demo):
    token = csrf(na_demo)
    r = na_demo.post("/backup", data={"csrf_token": token})
    assert r.headers["content-type"].startswith("text/html") and "o backup" in r.text
    r = na_demo.post("/restaurar", data={"csrf_token": token, "confirmed": "on"},
                     files={"file": ("x.sqlite3", b"nada", "application/octet-stream")})
    assert "restaurar backup" in r.text
    assert not (db.data_dir() / "backups").exists()


def test_recomecar_desfaz_o_que_foi_mexido_na_demo(na_demo):
    token = csrf(na_demo)
    na_demo.post("/configuracoes/titulares", data={"csrf_token": token, "name": "Visitante"})
    assert "Visitante" in na_demo.get("/configuracoes").text
    r = na_demo.post("/demo/recomecar", data={"csrf_token": token})
    assert ("success", "Demonstração recomeçada: tudo voltou ao original.") in avisos(r.text)
    assert "Visitante" not in na_demo.get("/configuracoes").text


def test_recomecar_fora_da_demo_nao_faz_nada(client):
    client.post("/demo/recomecar", data={"csrf_token": csrf(client)})
    assert not demo.path().exists()


def test_titular_escolhido_nao_passa_de_um_mundo_para_o_outro(client):
    household.add_member("Ana")
    token = csrf(client)
    client.post("/titular", data={"csrf_token": token, "member": "Ana"})
    client.post("/demo/entrar", data={"csrf_token": token})
    assert "Mostrando só" not in client.get("/").text


# ---------------------------------------------------------------- todas as telas com dados

@pytest.mark.parametrize("rota", ROTAS_GET)
@pytest.mark.parametrize("visao", ["casa", "Marina"])
def test_toda_pagina_tem_dados_na_demo(na_demo, rota, visao):
    na_demo.post("/titular", data={"csrf_token": csrf(na_demo), "member": visao})
    resposta = na_demo.get(rota)
    assert resposta.status_code == 200, f"{rota} respondeu {resposta.status_code}"
    html = _conteudo(resposta.text)
    assert "Demonstração · dados fictícios" in resposta.text
    if visao == "casa":
        vazios = [texto for texto in VAZIOS if texto in html]
        assert not vazios, f"{rota} aparece vazia na demo ({vazios}). Acrescente exemplos em app/demo.py."
        assert 'class="empty' not in html and "card empty" not in html, (
            f"{rota} tem um bloco vazio na demo. Acrescente exemplos em app/demo.py.")


def test_paginas_com_parametro_tem_dados_na_demo(na_demo):
    with demo.active():
        ativos = [a["ticker"] for a in analytics.Book().assets()]
        relatorios = [r[0] for r in db.rows("SELECT id FROM analysis_report")]
        categorias = {t["category"] for t in analytics.cash_transactions() if t["amount_cents"] < 0}
    assert len(ativos) >= 8 and len(relatorios) >= 6
    for caminho in [f"/ativo/{t}" for t in ativos] + [f"/analises/{i}" for i in relatorios] + [
        "/contas/gastos/" + quote(c) for c in categorias - {"Investimentos", "Pagamento de fatura", "Transferência própria",
                                                             "Transferência entre titulares"}
    ]:
        resposta = na_demo.get(caminho, follow_redirects=False)
        assert resposta.status_code == 200, f"{caminho} respondeu {resposta.status_code}"
        html = _conteudo(resposta.text)
        assert not [t for t in VAZIOS if t in html], caminho


# ---------------------------------------------------------------- coerência dos dados

@pytest.fixture
def base_demo():
    demo.build()
    with demo.active():
        yield


def test_demo_mostra_a_gestao_a_dois(base_demo):
    assert [m["name"] for m in household.members()] == ["Lucas", "Marina"]
    assert all(m["has_document"] for m in household.members())
    assert [len(c["items"]) for c in household.connections()] == [2, 1]
    movs = analytics.cash_transactions()
    pix = [t for t in movs if t["description"].startswith(("Pix enviado|Marina", "Pix recebido|Lucas"))]
    assert pix and {t["category"] for t in pix} == {"Transferência entre titulares"}
    assert analytics.Book(2).cash_at(date.today().isoformat()) > 0


def test_demo_tem_contas_que_nunca_ficam_no_vermelho(base_demo):
    serie = analytics.Book().series()
    assert len(serie) > 200
    assert min(p["cash"] for p in serie) > 0


def test_demo_tem_o_que_a_conciliacao_mostra(base_demo):
    status = {r["ticker"]: r["status"] for r in db.rows("SELECT ticker, status FROM v_position_reconciliation")}
    assert status.pop("TAEE11") == "DIVERGENT" and set(status.values()) == {"OK"}
    movs = analytics.cash_transactions()
    assert [t["description"] for t in analytics.unmatched_transfers(movs, "2000-01-01")] == ["Transferência para conta Inter"]
    assert db.rows("SELECT COUNT(*) FROM reconciliation_note")[0][0] == 1


def test_demo_tem_carteira_completa(base_demo):
    ativos = {a["ticker"]: a for a in analytics.Book().assets()}
    assert {a["asset_class"] for a in ativos.values()} == {"Ação", "FII", "ETF"}
    assert ativos["PETR4"]["qty"] == 0 and ativos["PETR4"]["realized"] != 0
    assert all(a["income_12m"] > 0 for t, a in ativos.items() if t not in {"IVVB11", "PETR4"})
    produtos = {p["product_type"] for p in analytics.Book().fixed_income(include_pension=True)}
    assert produtos == {"CDB", "LCI", "Tesouro", "Caixinha", "Previdência"}


def test_demo_e_sempre_igual(tmp_path):
    def resumo():
        demo.build()
        with demo.active():
            return (_contagens(), sum(t["amount_cents"] for t in analytics.cash_transactions()),
                    [(a["ticker"], a["value"]) for a in analytics.Book().assets()])
    assert resumo() == resumo()


def test_demo_se_refaz_em_outra_versao_ou_outro_dia(monkeypatch):
    demo.ensure()
    assert demo.is_fresh()
    criada = demo.path().stat().st_mtime_ns
    demo.ensure()
    assert demo.path().stat().st_mtime_ns == criada
    monkeypatch.setattr(demo, "__version__", "99.0.0")
    assert not demo.is_fresh()
    demo.ensure()
    assert demo.is_fresh()


def test_demo_nao_deixa_arquivo_temporario():
    demo.build()
    assert sorted(p.name for p in db.data_dir().iterdir() if p.name.startswith("demo")) == ["demo.sqlite3"]


def test_backup_da_demo_seria_valido():
    demo.build()
    ok, motivo = db.validate_database(demo.path())
    assert ok, motivo


# ---------------------------------------------------------------- linha de comando

def test_cli_na_demo(capsys, dados_exemplo):
    antes = _contagens()
    cli.main(["--demo", "carteira", "contexto"])
    saida = json.loads(capsys.readouterr().out)
    assert saida["titular"] == "casa" and saida["titulares"] == ["Lucas", "Marina"]
    assert len(saida["renda_variavel"]["posicoes"]) >= 8
    cli.main(["--demo", "--titular", "Marina", "gastos", "listar", "--limite", "3"])
    assert {t["titular"] for t in json.loads(capsys.readouterr().out)["lancamentos"]} == {"Marina"}
    assert _contagens() == antes


@pytest.mark.parametrize("comando", [["atualizar"], ["backup"]])
def test_cli_recusa_atualizar_e_backup_na_demo(capsys, comando):
    with pytest.raises(SystemExit):
        cli.main(["--demo", *comando])
    assert "demonstração" in json.loads(capsys.readouterr().out)["erro"]


def test_botao_da_demo_aparece_nas_boas_vindas(client):
    pagina = client.get("/").text
    assert "Bem-vindo ao Tabimoney" in pagina
    assert re.search(r'action="/demo/entrar"', pagina) and "Ver demonstração" in pagina


def test_botao_da_demo_fica_nas_configuracoes(client, dados_exemplo):
    assert 'action="/demo/entrar"' not in client.get("/").text
    pagina = client.get("/configuracoes").text
    assert re.search(r'action="/demo/entrar"', pagina) and "Ver demonstração" in pagina


def test_demo_exercita_historico_acima_de_tres_anos(base_demo):
    book = analytics.Book()
    assert len(book.monthly_returns(months=None)) > 36
    flow = analytics.cash_flow(analytics.cash_transactions(), months=None)
    assert len(flow) > 36
    assert book.series(full_history=True)[0]['d'] < book.series()[0]['d']
