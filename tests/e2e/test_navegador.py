"""O app num navegador de verdade: menus, gráficos, JavaScript, formulários e a tela do celular.

Os testes com TestClient (tests/test_paginas.py) garantem que o HTML sai sem erro; estes garantem que a página
funciona: o JavaScript roda sem erro, os botões fazem o que dizem e nada estoura a largura da tela.
O servidor é compartilhado pela sessão, então quem grava algo usa um nome só dele.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

MENU = [
    ("Visão geral", "/"), ("Ações e FIIs", "/carteira"), ("Recomendações", "/recomendacoes"),
    ("Renda fixa", "/renda-fixa"), ("Proventos e CDI", "/rendimentos"), ("Previdência", "/previdencia"),
    ("Metas", "/metas"), ("Conta e cartão", "/contas"), ("Importar", "/importar"), ("Conciliação", "/conciliacao"),
    ("Configurações", "/configuracoes"),
]


def _aviso(page: Page):
    """O aviso do que acabou de ser feito. Fica na primeira pilha; algumas páginas têm outra, de alertas."""
    return page.locator(".flash-stack").first


# ---------------------------------------------------------------- navegação

def test_menu_abre_todas_as_paginas_sem_erro_de_javascript(page: Page, base_url):
    page.goto("/")
    for rotulo, caminho in MENU:
        page.locator("nav.nav a", has_text=rotulo).click()
        expect(page).to_have_url(base_url + caminho)
        expect(page.locator("nav.nav a[aria-current=page]")).to_have_text(re.compile(rotulo))
        expect(page.locator("h1")).to_be_visible()


@pytest.mark.parametrize("caminho", ["/", "/contas", "/carteira", "/rendimentos"])
def test_graficos_desenham(page: Page, caminho):
    page.goto(caminho)
    graficos = page.locator("[data-chart]")
    assert graficos.count() > 0
    for i in range(graficos.count()):
        grafico = graficos.nth(i)
        if grafico.is_visible():
            expect(grafico.locator("svg, .chart-empty").first).to_be_attached()


def test_ativo_abre_pelo_link_da_carteira(page: Page, base_url):
    page.goto("/carteira")
    page.get_by_role("link", name="ITSA4").first.click()
    expect(page).to_have_url(re.compile(re.escape(base_url + "/ativo/ITSA4") + r"(#.*)?$"))
    expect(page.locator("h1")).to_contain_text("ITSA4")


# ---------------------------------------------------------------- titulares

def test_seletor_de_titular_filtra_e_volta_para_a_casa(page: Page):
    page.goto("/contas")
    seletor = page.locator(".member-switch")
    expect(seletor.get_by_role("button", name="Casa")).to_have_attribute("aria-pressed", "true")
    tabela = page.locator("#tx")
    expect(tabela).to_contain_text("Carrefour Hiper")
    expect(tabela).to_contain_text("Supermercado Pão de Açúcar")

    seletor.get_by_role("button", name="Marina").click()
    expect(page).to_have_url(re.compile(r"/contas$"))
    expect(page.locator(".member-note")).to_contain_text("Marina")
    expect(seletor.get_by_role("button", name="Marina")).to_have_attribute("aria-pressed", "true")
    expect(tabela).to_contain_text("Carrefour Hiper")
    expect(tabela).not_to_contain_text("Supermercado Pão de Açúcar")

    seletor.get_by_role("button", name="Casa").click()
    expect(page.locator(".member-note")).to_have_count(0)
    expect(tabela).to_contain_text("Supermercado Pão de Açúcar")


def test_carteira_do_titular_so_mostra_a_quantidade_dele(page: Page):
    page.goto("/ativo/ITSA4")
    expect(page.locator("main")).to_contain_text("1100")  # 800 do Lucas + 300 da Marina
    page.locator(".member-switch").get_by_role("button", name="Marina").click()
    expect(page.locator("main")).to_contain_text("300")
    expect(page.locator("main")).not_to_contain_text("1100")


def test_cadastrar_e_excluir_titular(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#titulares")
    novo = page.locator("form[action='/configuracoes/titulares']")
    novo.get_by_label("Novo titular").fill("Bia")
    novo.get_by_role("button", name="Adicionar titular").click()
    expect(_aviso(page)).to_contain_text("Bia cadastrado(a) como titular.")
    expect(page.locator(".member-switch").get_by_role("button", name="Bia")).to_be_visible()

    page.get_by_role("button", name="Excluir Bia").click()
    expect(_aviso(page)).to_contain_text("Titular excluído.")
    expect(page.locator(".member-switch").get_by_role("button", name="Bia")).to_have_count(0)


def test_cpf_invalido_mostra_erro(page: Page):
    page.goto("/configuracoes#titulares")
    novo = page.locator("form[action='/configuracoes/titulares']")
    novo.get_by_label("Novo titular").fill("Caio")
    novo.get_by_label("CPF (opcional)").fill("123.456.789-00")
    novo.get_by_role("button", name="Adicionar titular").click()
    expect(page.locator(".flash-error")).to_contain_text("CPF inválido")


# ---------------------------------------------------------------- conexões Pluggy

def test_criar_e_excluir_conexao_pluggy(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#open-finance")
    page.get_by_text("Nova conexão (outro Client ID e Secret)").click()
    nova = page.locator("details form[action='/configuracoes/pluggy']")
    nova.get_by_label("Nome da conexão", exact=True).fill("Pluggy E2E")
    nova.get_by_label("Client ID", exact=True).fill("id-e2e")
    nova.get_by_label("Client Secret", exact=True).fill("segredo-e2e")
    nova.get_by_label("Item IDs", exact=True).fill("44444444-4444-4444-8444-444444444444")
    nova.get_by_label("Titular dos Item IDs").select_option(label="Marina")
    nova.get_by_role("button", name="Criar conexão").click()
    expect(_aviso(page)).to_contain_text("Conexão salva.")

    cartao = page.locator("form[action='/configuracoes/pluggy']", has=page.locator("input[value='Pluggy E2E']"))
    expect(cartao).to_contain_text("item 44444444")
    expect(cartao).to_contain_text("Marina")
    expect(cartao.locator(".status-line", has_text="Client ID")).to_contain_text("Configurada")
    expect(page.locator("body")).not_to_contain_text("segredo-e2e")

    page.locator("form[action='/configuracoes/pluggy/excluir']").last.get_by_role("button", name="Excluir conexão").click()
    expect(_aviso(page)).to_contain_text("Conexão excluída.")
    expect(page.locator("input[value='Pluggy E2E']")).to_have_count(0)


def test_sincronizar_sem_internet_avisa_sem_quebrar(page: Page):
    page.goto("/")
    botao = page.get_by_role("button", name=re.compile("Open Finance"))
    if botao.count() == 0:
        pytest.skip("botão de sincronização não está na visão geral")
    botao.first.click()
    expect(page.locator(".flash-stack .flash").first).to_be_visible()
    expect(page.locator("h1")).to_be_visible()


# ---------------------------------------------------------------- gastos e metas

def test_recategorizar_pela_tabela(page: Page):
    page.goto("/contas#movimentacoes")
    linha = page.locator("#tx tbody tr", has_text="Uber").first
    linha.locator("select[name=category]").select_option("Lazer")
    expect(_aviso(page)).to_contain_text("Categoria alterada para Lazer.")
    expect(page.locator("#tx tbody tr", has_text="Uber").first.locator("select[name=category]")).to_have_value("Lazer")


def test_busca_da_tabela_filtra_sem_recarregar(page: Page):
    page.goto("/contas#movimentacoes")
    page.get_by_label("Buscar movimentações").fill("anthropic")
    visiveis = page.locator("#tx tbody tr:visible")
    expect(visiveis.first).to_contain_text("Anthropic")
    assert all("Anthropic" in t for t in visiveis.all_inner_texts())


def test_metas_do_titular_e_da_casa(page: Page):
    page.goto("/metas")
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("40")
    page.locator(".member-switch").get_by_role("button", name="Marina").click()
    expect(page.get_by_role("heading", name="Definir metas de Marina")).to_be_visible()
    expect(page.locator("main")).to_contain_text("Marina tem metas próprias")
    page.get_by_label("Renda fixa (%)").fill("70")
    page.get_by_label("Renda variável (%)").fill("30")
    page.get_by_role("button", name="Salvar metas").click()
    expect(_aviso(page)).to_contain_text("Metas de Marina salvas.")
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("70")

    page.get_by_role("button", name="Usar as metas da casa").click()
    expect(_aviso(page)).to_contain_text("voltou a usar as metas da casa")
    expect(page.locator("main")).to_contain_text("Marina ainda usa as metas da casa")
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("40")
    page.locator(".member-switch").get_by_role("button", name="Casa").click()
    expect(page.get_by_role("heading", name="Definir metas da casa")).to_be_visible()


# ---------------------------------------------------------------- dados em todas as telas

@pytest.mark.parametrize("caminho", [c for _, c in MENU])
def test_nenhum_grafico_vazio(page: Page, caminho):
    """O servidor de teste usa os dados da demonstração: todo gráfico tem o que desenhar."""
    page.goto(caminho)
    expect(page.locator(".chart-empty")).to_have_count(0)


def test_ver_demonstracao_pela_visao_geral(aceitar_confirmacoes: Page, base_url):
    page = aceitar_confirmacoes
    page.goto("/")
    page.get_by_role("button", name="Ver demonstração").click()
    faixa = page.locator(".demo-banner")
    expect(faixa).to_contain_text("Demonstração · dados fictícios")
    expect(page.locator("h1")).to_have_text("Olá, Lucas!")
    for _, caminho in MENU:
        page.goto(caminho)
        expect(faixa).to_be_visible()
        expect(page.locator(".chart-empty")).to_have_count(0)

    page.goto("/configuracoes#titulares")
    page.locator("form[action='/configuracoes/titulares']").get_by_label("Novo titular").fill("Visitante")
    page.get_by_role("button", name="Adicionar titular").click()
    expect(page.locator(".member-switch")).to_contain_text("Visitante")
    faixa.get_by_role("button", name="Recomeçar").click()
    expect(_aviso(page)).to_contain_text("Demonstração recomeçada")
    expect(page.locator(".member-switch")).not_to_contain_text("Visitante")

    page.get_by_role("button", name="Open Finance").click()
    expect(_aviso(page)).to_contain_text("Na demonstração, sincronizar o Open Finance fica desligado")

    faixa.get_by_role("button", name="Sair da demo").click()
    expect(page.locator(".demo-banner")).to_have_count(0)
    expect(page.get_by_role("button", name="Ver demonstração")).to_be_visible()


# ---------------------------------------------------------------- celular

@pytest.mark.parametrize("caminho", [c for _, c in MENU])
def test_celular_sem_rolagem_horizontal(page: Page, caminho):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(caminho)
    largura = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert largura <= 1, f"{caminho} passa {largura}px da largura do celular"
