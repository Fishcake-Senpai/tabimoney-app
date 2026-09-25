"""Formulários principais pela interface: salvam o que devem e voltam com o aviso certo."""
from __future__ import annotations

from urllib.parse import quote

from app import db, security
from app.services import analytics, budgets, spending

from .conftest import avisos, csrf


def test_salvar_configuracoes_guarda_segredos_no_cofre(client, cofre):
    r = client.post("/configuracoes", data={
        "csrf_token": csrf(client), "pluggy_client_id": " id-123 ", "pluggy_client_secret": "segredo",
        "pluggy_item_ids": "0f8fad5b-d9cb-469f-a165-70867728950e, nao-e-uuid", "brapi_token": "tok",
        "daily_quotes": "on", "update_check": "on", "display_name": "Ana",
    })
    assert cofre.dados[(security.SERVICE_NAME, "pluggy_client_id")] == "id-123"
    assert cofre.dados[(security.SERVICE_NAME, "brapi_token")] == "tok"
    assert db.get_setting("pluggy_item_ids") == "0f8fad5b-d9cb-469f-a165-70867728950e"
    tipos = dict(avisos(r.text))
    assert "warning" in tipos and "nao-e-uuid" in tipos["warning"]
    assert "Configurada" in client.get("/configuracoes").text


def test_formulario_sem_csrf_e_recusado(client):
    assert client.post("/configuracoes", data={"csrf_token": "falso"}).status_code == 403


def test_recategorizar_pela_tabela_volta_para_a_pagina_de_origem(client, dados_exemplo):
    uber = next(t for t in analytics.cash_transactions() if t["description"] == "Uber")
    r = client.post("/contas/categoria", data={
        "csrf_token": csrf(client), "transaction_id": uber["id"], "category": "Lazer",
        "back": "/contas/gastos/" + quote("Transporte"),
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/contas/gastos/")
    assert next(t for t in analytics.cash_transactions() if t["id"] == uber["id"])["category"] == "Lazer"


def test_criar_e_excluir_categoria_pela_interface(client, dados_exemplo):
    token = csrf(client)
    assert ("success", "Categoria Delivery criada.") in avisos(
        client.post("/contas/categorias", data={"csrf_token": token, "name": "Delivery"}).text)
    assert ("warning", "A categoria Delivery já existe.") in avisos(
        client.post("/contas/categorias", data={"csrf_token": token, "name": "delivery"}).text)
    ifood = [t["id"] for t in analytics.cash_transactions() if t["description"] == "iFood"][:2]
    spending.set_category(ifood, "Delivery")
    bloqueio = avisos(client.post("/contas/categorias/excluir", data={"csrf_token": token, "name": "Delivery"}).text)
    assert bloqueio and bloqueio[0][0] == "error" and "em uso" in bloqueio[0][1]
    ok = avisos(client.post("/contas/categorias/excluir",
                            data={"csrf_token": token, "name": "Delivery", "destination": "Outros"}).text)
    assert ok[0][0] == "success"
    assert "Delivery" not in spending.known_categories()
    client.post("/contas/categorias/restaurar", data={"csrf_token": token, "name": "Delivery"})
    assert "Delivery" in spending.known_categories()


def test_meta_de_gasto_criar_e_excluir(client, dados_exemplo):
    token = csrf(client)
    client.post("/orcamento", data={"csrf_token": token, "name": "Comer fora", "limit": "1.200,00",
                                    "alert_pct": "80", "categories": ["Alimentação"]})
    meta = next(b for b in budgets.budgets() if b["name"] == "Comer fora")
    assert meta["monthly_limit_cents"] == 120000 and meta["categories"] == ["Alimentação"]
    client.post("/orcamento/excluir", data={"csrf_token": token, "budget_id": meta["id"]})
    assert not budgets.budgets()


def test_encerrar_sem_launcher_nao_derruba_o_app(client):
    r = client.post("/sistema/encerrar", data={"csrf_token": csrf(client)})
    assert r.status_code == 200 and "Ctrl+C" in r.text


def test_encerramento_do_launcher_exige_token(client):
    assert client.post("/_sistema/encerrar", headers={"X-Tabimoney-Token": "errado"}).status_code == 403
