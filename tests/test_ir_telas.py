"""Telas de Imposto de renda e o bloco de aportes da Previdência: formulários, aviso de regras no sino e o que a
estimativa mostra depois de cada cadastro."""
from __future__ import annotations

from datetime import date

from app import db
from app.services import pension
from app.services.ir import estimador, parametros

from .conftest import avisos, csrf

ANO = date.today().year


def _fonte(client, **campos):
    dados = {"csrf_token": csrf(client), "ano": ANO, "kind": "clt", "payer": "Empresa SA", "gross": "12.000,00",
             "first_month": "1", "last_month": "12", "thirteenth": "on", **campos}
    return client.post("/imposto-de-renda/fonte", data=dados)


def test_cadastrar_renda_mostra_o_imposto_e_o_pgbl(client):
    vazia = client.get("/imposto-de-renda").text
    assert "Quanto você ganha?" in vazia
    pagina = _fonte(client).text
    assert ("success", "Fonte de renda salva.") in avisos(pagina)
    assert "Completo ou simplificado" in pagina and "PGBL: quanto ainda cabe" in pagina
    assert "R$ 17,3 mil" in pagina            # limite do PGBL: 12% de 144 mil
    fonte = estimador.fontes(1, ANO)[0]
    assert fonte["gross_monthly_cents"] == 1_200_000 and fonte["thirteenth"] == 1


def test_renda_invalida_avisa(client):
    pagina = _fonte(client, gross="").text
    assert any(kind == "error" for kind, _ in avisos(pagina))
    assert estimador.fontes(1, ANO) == []


def test_dependente_entra_e_sai(client):
    _fonte(client)
    pagina = client.post("/imposto-de-renda/dependente", data={"csrf_token": csrf(client), "ano": ANO, "name": "Bia",
                                                               "kinship": "filho", "birth_year": "2015"}).text
    assert "Bia" in pagina and estimador.dependentes(1, ANO)[0]["name"] == "Bia"
    dep = estimador.dependentes(1, ANO)[0]["id"]
    client.post("/imposto-de-renda/dependente", data={"csrf_token": csrf(client), "ano": ANO, "remove_id": dep})
    assert estimador.dependentes(1, ANO) == []


def _gasto(descricao: str, centavos: int, categoria: str) -> int:
    with db.transaction() as con:
        con.execute("INSERT OR IGNORE INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
                    "VALUES (1, 'Nubank', 'Nubank', 'BANK', 'pluggy', 'k1')")
        cur = con.execute("INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
                          "amount_cents, category) VALUES (1, 'pluggy', ?, ?, ?, ?, ?)",
                          (f"x{descricao}", f"{ANO}-01-15", descricao, centavos, categoria))
        return int(cur.lastrowid)


def test_categoria_saude_e_marcacao_do_lancamento(client):
    consulta = _gasto("Consulta Dr. Paulo", -40_000, "Saúde")
    _gasto("Drogasil", -5_000, "Saúde")
    pagina = client.get(f"/imposto-de-renda/deducoes?ano={ANO}").text
    assert "Categorias que podem deduzir" in pagina and "Contar como saúde" in pagina
    pagina = client.post("/imposto-de-renda/categoria", data={"csrf_token": csrf(client), "category": "Saúde",
                                                              "kind": "saude", "ano": ANO}).text
    assert "Consulta Dr. Paulo" in pagina and "Farmácia não é dedutível" in pagina
    client.post("/imposto-de-renda/deducao", data={"csrf_token": csrf(client), "ano": ANO, "transaction_id": consulta,
                                                   "kind": "saude", "beneficiary": "titular", "provider": "Dr. Paulo",
                                                   "provider_doc": "52998224725", "reimbursed": "100"})
    item = next(i for i in estimador.deducoes(1, ANO)["itens"] if i["id"] == consulta)
    assert item["documento"] == "52998224725" and item["conta"] == 30_000


def test_despesa_fora_do_extrato(client):
    pagina = client.post("/imposto-de-renda/deducao/manual", data={
        "csrf_token": csrf(client), "ano": ANO, "kind": "educacao", "paid_on": f"{ANO}-03-01", "amount": "2.500,00",
        "provider": "Escola X", "provider_doc": "", "beneficiary": "titular"}).text
    assert ("success", "Despesa dedutível incluída.") in avisos(pagina)
    item = estimador.deducoes(1, ANO)["itens"][0]
    client.post("/imposto-de-renda/deducao/manual/excluir", data={"csrf_token": csrf(client), "ano": ANO,
                                                                  "deduction_id": item["id"]})
    assert estimador.deducoes(1, ANO)["itens"] == []


def test_aporte_da_empresa_e_do_participante_na_previdencia(client):
    pension.save_entry({"name": "Plano PGBL", "institution": "Itaú", "plan_type": "PGBL", "as_of_date": f"{ANO}-01-31",
                        "gross": "1000"})
    _fonte(client)
    key = estimador.planos()[0]["product_key"]
    client.post("/previdencia/aporte", data={"csrf_token": csrf(client), "product_key": key, "paid_on": f"{ANO}-01-10",
                                             "amount": "1.000,00", "payer": "empresa", "repeat": "on"})
    pagina = client.post("/previdencia/aporte", data={"csrf_token": csrf(client), "product_key": key,
                                                      "paid_on": f"{ANO}-02-10", "amount": "2.000,00",
                                                      "payer": "participante"}).text
    assert "Aportes de" in pagina and "empresa (não deduz)" in pagina
    prev = estimador.estimar(1, ANO)["previdencia"]
    assert prev["participante"] == 200_000 and prev["empresa"] == 1_200_000
    assert prev["falta"] == 1_728_000 - 200_000


def test_pendencia_de_classe_e_prejuizo_anterior(client):
    with db.transaction() as con:
        con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
                    "VALUES (9, 'XP', 'XP', 'INVESTMENT', 'b3', 'xp')")
        con.execute("INSERT INTO instrument(id, ticker, name, asset_class) VALUES (9, 'XPTO11', 'XPTO', 'FII/ETF/Unit')")
        for n, (tipo, qtd, valor, dia) in enumerate((("BUY", 10, 100_000, f"{ANO}-01-05"), ("SELL", -10, 120_000, f"{ANO}-02-05"))):
            con.execute("INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, event_type, "
                        "quantity_micros, amount_cents) VALUES (9, 9, 'b3', ?, ?, ?, ?, ?)",
                        (f"e{n}", dia, tipo, qtd * 1_000_000, valor))
    pagina = client.get(f"/imposto-de-renda/acoes?ano={ANO}").text
    assert "Classe do ativo" in pagina and "Prejuízo de anos anteriores" in pagina
    client.post("/imposto-de-renda/pendencia", data={"csrf_token": csrf(client), "ano": ANO, "kind": "classe",
                                                     "ticker": "XPTO11", "tax_class": "fii"})
    pagina = client.post("/imposto-de-renda/pendencia", data={"csrf_token": csrf(client), "ano": ANO,
                                                              "kind": "prejuizo_anterior", "period": ANO}).text
    assert "Classe do ativo" not in pagina and "Prejuízo de anos anteriores" not in pagina
    assert "FII" in pagina and "R$ 40,00" in pagina      # 20% de 200 de lucro em FII


def test_aviso_de_regras_desatualizadas_no_sino_e_na_tela(client, monkeypatch):
    monkeypatch.setattr(parametros, "EXERCICIO_CONFIRMADO", 2020)
    inicio = client.get("/").text
    assert "Regras do IR" in inicio and "podem estar desatualizadas" in inicio
    assert 'id="aviso-regras"' in client.get("/imposto-de-renda").text
    monkeypatch.setattr(parametros, "EXERCICIO_CONFIRMADO", 2100)   # versão nova trouxe a revisão: o aviso some
    assert "Regras do IR" not in client.get("/").text


def test_declaracao_mostra_fichas_com_copiar(client):
    _fonte(client)
    pagina = client.get(f"/imposto-de-renda/declaracao?ano={ANO}").text
    assert "Rendimentos tributáveis recebidos de pessoa jurídica" in pagina
    assert 'data-copy="cp-' in pagina and "Antes de começar" in pagina
