"""Todas as páginas abrem, com a base vazia e com dados.

A lista de rotas vem do próprio app: página nova entra aqui sozinha. Pega, por exemplo, template que usa uma
variável que a rota não envia (UndefinedError), que só aparece ao abrir a página.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi.routing import APIRoute

from app.main import app

ROTAS_GET = sorted(
    r.path for r in app.routes
    if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
)
ROTAS_COM_PARAMETRO = sorted(
    r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods and "{" in r.path
)


def test_descobriu_as_paginas_principais():
    for pagina in ("/", "/contas", "/configuracoes", "/carteira", "/metas", "/importar"):
        assert pagina in ROTAS_GET


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_pagina_abre_com_base_vazia(client, rota):
    resposta = client.get(rota)
    assert resposta.status_code == 200, f"{rota} respondeu {resposta.status_code}"


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_pagina_abre_com_dados(client, dados_exemplo, rota):
    resposta = client.get(rota)
    assert resposta.status_code == 200, f"{rota} respondeu {resposta.status_code}"


@pytest.mark.parametrize("rota", ROTAS_COM_PARAMETRO)
def test_rota_com_parametro_inexistente_nao_quebra(client, rota):
    """Ticker, relatório ou categoria que não existem: pode redirecionar ou dar 404, nunca erro 500."""
    caminho = rota.replace("{report_id}", "999999")
    for nome in ("{ticker}", "{category:path}", "{category}"):
        caminho = caminho.replace(nome, "NAOEXISTE3")
    resposta = client.get(caminho, follow_redirects=False)
    assert resposta.status_code in (200, 303, 307, 404), f"{caminho} respondeu {resposta.status_code}"


def test_pagina_de_categoria_com_dados(client, dados_exemplo):
    pagina = client.get("/contas/gastos/" + quote("Alimentação"))
    assert pagina.status_code == 200
    assert 'id="data-category"' in pagina.text
    assert "fatura aberta" in pagina.text  # a compra PENDING do cartão aparece na lista


def test_link_para_categoria_na_tabela_mes_a_mes(client, dados_exemplo):
    assert 'href="/contas/gastos/Alimenta%C3%A7%C3%A3o"' in client.get("/contas").text


def test_valor_original_em_dolar_aparece(client, dados_exemplo):
    assert "US$ 21,00" in client.get("/contas/gastos/Assinaturas").text


def test_configuracoes_mostra_cofre_e_atualizacoes(client):
    from app.security import vault_name

    pagina = client.get("/configuracoes").text
    assert vault_name() in pagina
    assert 'id="atualizacoes"' in pagina


def test_acesso_de_fora_da_maquina_e_recusado(client):
    resposta = client.get("/", headers={"host": "exemplo.com"})
    assert resposta.status_code == 400
