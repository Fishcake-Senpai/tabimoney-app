"""O app num navegador de verdade: menus, gráficos, JavaScript, formulários e a tela do celular.

Os testes com TestClient (tests/test_paginas.py) garantem que o HTML sai sem erro; estes garantem que a página
funciona: o JavaScript roda sem erro, os botões fazem o que dizem e nada estoura a largura da tela.
O servidor é compartilhado pela sessão, então quem grava algo usa um nome só dele.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

MENU = [("Início", "/"), ("Gastos", "/contas"), ("Investimentos", "/investimentos"), ("Sugestões", "/recomendacoes"),
        ("Configurações", "/configuracoes")]
ABAS_INVESTIMENTOS = [("Ações e FIIs", "/carteira"), ("Renda fixa", "/renda-fixa"), ("Previdência", "/previdencia"),
                      ("Proventos", "/rendimentos"), ("Metas", "/metas"), ("Resumo", "/investimentos")]
ABAS_GASTOS = [("Lançamentos", "/contas/lancamentos"), ("Orçamento", "/contas/orcamento"), ("Resumo", "/contas")]
PAGINAS = [c for _, c in MENU] + [c for _, c in ABAS_INVESTIMENTOS + ABAS_GASTOS if c not in {"/investimentos", "/contas"}] + [
    "/conciliacao", "/importar", "/analises", "/ativo/EGIE3", "/contas/gastos/Mercado"]


def _aviso(page: Page):
    """O aviso do que acabou de ser feito (o toast no canto)."""
    return page.locator(".flash-stack").first


def _titular(page: Page, nome: str):
    """Troca a visão pelo menu de titular da barra do topo."""
    page.locator(".member-btn").click()
    page.locator(".member-switch").get_by_role("button", name=nome).click()


# ---------------------------------------------------------------- navegação

def test_menu_abre_todas_as_paginas_sem_erro_de_javascript(page: Page, base_url):
    page.goto("/")
    for rotulo, caminho in MENU:
        page.locator(".sidebar nav.nav a", has_text=rotulo).click()
        expect(page).to_have_url(base_url + caminho)
        expect(page.locator(".sidebar a[aria-current=page]")).to_have_text(re.compile(rotulo))
        expect(page.locator("h1")).to_be_visible()


def test_abas_de_investimentos_e_de_gastos(page: Page, base_url):
    page.goto("/investimentos")
    for rotulo, caminho in ABAS_INVESTIMENTOS:
        page.locator("nav.tabs a", has_text=rotulo).click()
        expect(page).to_have_url(base_url + caminho)
        expect(page.locator("nav.tabs a[aria-current=page]")).to_have_text(rotulo)
        expect(page.locator(".sidebar a[aria-current=page]")).to_have_text(re.compile("Investimentos"))
    page.goto("/contas")
    for rotulo, caminho in ABAS_GASTOS:
        page.locator("nav.tabs a", has_text=rotulo).click()
        expect(page).to_have_url(base_url + caminho)
        expect(page.locator(".sidebar a[aria-current=page]")).to_have_text(re.compile("Gastos"))


@pytest.mark.parametrize("caminho", ["/", "/investimentos", "/carteira"])
def test_cards_clicaveis_levam_a_pagina_certa(page: Page, base_url, caminho):
    page.goto(caminho)
    destinos = page.locator("a.stat").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert destinos and all(d.startswith("/") and '"' not in d for d in destinos), destinos
    for i, destino in enumerate(destinos):
        page.goto(caminho)
        page.locator("a.stat").nth(i).click()
        expect(page).to_have_url(base_url + destino)
        expect(page.locator("h1")).to_be_visible()


@pytest.mark.parametrize("caminho", ["/", "/contas", "/investimentos", "/carteira", "/rendimentos"])
def test_graficos_desenham(page: Page, caminho):
    page.goto(caminho)
    graficos = page.locator("[data-chart]")
    assert graficos.count() > 0
    for i in range(graficos.count()):
        grafico = graficos.nth(i)
        if grafico.is_visible():
            expect(grafico.locator("svg, .chart-empty").first).to_be_attached()


def test_legenda_liga_e_desliga_a_serie(page: Page):
    page.goto("/carteira")
    card = page.locator(".card", has=page.locator("[data-chart=returns]"))
    cdi = card.locator(".legend button", has_text="CDI")
    expect(cdi).to_have_attribute("aria-pressed", "true")
    cdi.click()
    expect(card.locator(".legend button", has_text="CDI")).to_have_attribute("aria-pressed", "false")


def test_ativo_abre_pelo_link_da_carteira(page: Page, base_url):
    page.goto("/carteira")
    page.get_by_role("link", name="ITSA4").first.click()
    expect(page).to_have_url(re.compile(re.escape(base_url + "/ativo/ITSA4") + r"(#.*)?$"))
    expect(page.locator("h1")).to_contain_text("ITSA4")
    page.locator("nav.tabs a", has_text="Eventos").click()
    expect(page.locator("main")).to_contain_text("Compra")


def test_mais_colunas_na_carteira(page: Page):
    page.goto("/carteira")
    coluna = page.locator("#positions th", has_text="Preço médio")
    expect(coluna).to_be_hidden()
    page.get_by_role("button", name="Mais colunas").click()
    expect(coluna).to_be_visible()
    page.reload()
    expect(page.locator("#positions th", has_text="Preço médio")).to_be_visible()  # a escolha fica guardada
    page.get_by_role("button", name="Mais colunas").click()


# ---------------------------------------------------------------- titulares

def test_seletor_de_titular_filtra_e_volta_para_a_casa(page: Page):
    page.goto("/contas/lancamentos")
    lista = page.locator("#tx")
    expect(lista).to_contain_text("Carrefour Hiper")
    expect(lista).to_contain_text("Supermercado Pão de Açúcar")

    _titular(page, "Marina")
    expect(page).to_have_url(re.compile(r"/contas/lancamentos$"))
    expect(page.locator(".member-btn")).to_contain_text("Marina")
    expect(page.locator(".member-note")).to_contain_text("Marina")
    expect(lista).to_contain_text("Carrefour Hiper")
    expect(lista).not_to_contain_text("Supermercado Pão de Açúcar")

    _titular(page, "Casa")
    expect(page.locator(".member-note")).to_have_count(0)
    expect(lista).to_contain_text("Supermercado Pão de Açúcar")


def test_carteira_do_titular_so_mostra_a_quantidade_dele(page: Page):
    page.goto("/ativo/ITSA4")
    expect(page.locator("main")).to_contain_text("1100")  # 800 do Lucas + 300 da Marina
    _titular(page, "Marina")
    expect(page.locator("main")).to_contain_text("300")
    expect(page.locator("main")).not_to_contain_text("1100")
    _titular(page, "Casa")


def test_cadastrar_e_excluir_titular(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#titulares")
    page.get_by_role("button", name="Novo titular").click()
    novo = page.locator("form[action='/configuracoes/titulares']")
    novo.get_by_label("Novo titular").fill("Bia")
    novo.get_by_role("button", name="Adicionar titular").click()
    expect(_aviso(page)).to_contain_text("Bia cadastrado(a) como titular.")
    expect(page.locator(".member-switch button", has_text="Bia")).to_have_count(1)  # dentro do menu fechado

    page.get_by_role("button", name="Editar Bia").click()
    page.get_by_role("button", name="Excluir Bia").click()
    expect(_aviso(page)).to_contain_text("Titular excluído.")
    expect(page.locator(".member-switch button", has_text="Bia")).to_have_count(0)


def test_cpf_invalido_mostra_erro(page: Page):
    page.goto("/configuracoes#titulares")
    page.get_by_role("button", name="Novo titular").click()
    novo = page.locator("form[action='/configuracoes/titulares']")
    novo.get_by_label("Novo titular").fill("Caio")
    novo.get_by_label("CPF (opcional)").fill("123.456.789-00")
    novo.get_by_role("button", name="Adicionar titular").click()
    expect(page.locator(".flash-error")).to_contain_text("CPF inválido")


# ---------------------------------------------------------------- conexões Pluggy

def test_criar_e_excluir_conexao_pluggy(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#open-finance")
    page.get_by_role("button", name="Nova conexão").click()
    nova = page.locator("#dlg-pluggy-nova form")
    nova.get_by_label("Nome da conexão", exact=True).fill("Pluggy E2E")
    nova.get_by_label("Client ID", exact=True).fill("id-e2e")
    nova.get_by_label("Client Secret", exact=True).fill("segredo-e2e")
    nova.get_by_label("Item IDs", exact=True).fill("44444444-4444-4444-8444-444444444444")
    nova.get_by_label("Titular dos Item IDs").select_option(label="Marina")
    nova.get_by_role("button", name="Criar conexão").click()
    expect(_aviso(page)).to_contain_text("Conexão salva.")

    linha = page.locator("#open-finance .set-row", has_text="Pluggy E2E")
    expect(linha).to_contain_text("item 44444444 (Marina)")
    expect(linha.locator(".badge")).to_have_text("Conectada")
    expect(page.locator("body")).not_to_contain_text("segredo-e2e")

    linha.get_by_role("button", name="Editar conexão Pluggy E2E").click()
    modal = page.locator("dialog[open]")
    expect(modal.locator(".kv", has_text="Client ID")).to_contain_text("Configurada")
    modal.get_by_role("button", name="Excluir conexão").click()
    expect(_aviso(page)).to_contain_text("Conexão excluída.")
    expect(page.locator("input[value='Pluggy E2E']")).to_have_count(0)


def test_sincronizar_sem_internet_avisa_sem_quebrar(page: Page):
    page.goto("/contas")
    page.get_by_role("button", name="Sincronizar").click()
    expect(page).to_have_url(re.compile(r"/contas$"))
    expect(page.locator(".flash-stack .flash").first).to_be_visible()
    expect(page.locator("h1")).to_be_visible()


# ---------------------------------------------------------------- gastos e metas

def test_recategorizar_pelo_painel_do_lancamento(page: Page):
    page.goto("/contas/lancamentos")
    page.locator("button[data-tx]", has_text="Uber").first.click()
    painel = page.locator("#dlg-tx")
    expect(painel).to_be_visible()
    expect(painel).to_contain_text("Uber")
    painel.get_by_label("Trocar a categoria").select_option("Lazer")
    painel.get_by_role("button", name="Salvar").click()
    expect(_aviso(page)).to_contain_text("Categoria alterada para Lazer.")
    expect(page.locator("button[data-tx]", has_text="Uber").first).to_contain_text("Lazer")


def test_ultimo_lancamento_do_inicio_abre_o_painel(page: Page):
    page.goto("/")
    page.locator("a.row[href*='/contas/lancamentos#tx-']").first.click()
    expect(page).to_have_url(re.compile(r"/contas/lancamentos#tx-\d+$"))
    expect(page.locator("#dlg-tx")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#dlg-tx")).to_be_hidden()


def test_busca_da_lista_filtra_sem_recarregar(page: Page):
    page.goto("/contas/lancamentos")
    page.get_by_label("Buscar lançamentos").fill("anthropic")
    visiveis = page.locator("#tx [data-row]:visible")
    expect(visiveis.first).to_contain_text("Anthropic")
    assert all("Anthropic" in t for t in visiveis.all_inner_texts())
    expect(page.locator("[data-count-for=tx]")).not_to_contain_text("150")


def test_nova_meta_de_gasto_pelo_dialogo(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/contas/orcamento")
    page.get_by_role("button", name="Nova meta").click()
    dialogo = page.locator("#dlg-nova-meta")
    dialogo.get_by_label("Nome").fill("Meta E2E")
    dialogo.get_by_label("Limite por mês (R$)").fill("321")
    dialogo.get_by_label("Educação").check()
    dialogo.get_by_role("button", name="Criar meta").click()
    expect(_aviso(page)).to_contain_text('Meta "Meta E2E" salva')
    page.locator("details.fold summary", has_text="Todas as metas").click()
    page.locator("button.row", has_text="Meta E2E").click()
    page.locator("dialog[open]").get_by_role("button", name="Excluir meta").click()
    expect(_aviso(page)).to_contain_text("Meta de gasto excluída.")


def test_metas_do_titular_e_da_casa(page: Page):
    page.goto("/metas")
    page.get_by_role("button", name="Editar metas").click()
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("40")
    page.keyboard.press("Escape")
    _titular(page, "Marina")
    expect(page.locator("main")).to_contain_text("Marina tem metas próprias")
    page.get_by_role("button", name="Editar metas").click()
    expect(page.get_by_role("heading", name="Definir metas de Marina")).to_be_visible()
    page.get_by_label("Renda fixa (%)").fill("70")
    page.get_by_label("Renda variável (%)").fill("30")
    page.get_by_role("button", name="Salvar metas").click()
    expect(_aviso(page)).to_contain_text("Metas de Marina salvas.")
    page.get_by_role("button", name="Editar metas").click()
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("70")

    page.get_by_role("button", name="Usar as metas da casa").click()
    expect(_aviso(page)).to_contain_text("voltou a usar as metas da casa")
    expect(page.locator("main")).to_contain_text("Marina ainda usa as metas da casa")
    page.get_by_role("button", name="Editar metas").click()
    expect(page.get_by_label("Renda fixa (%)")).to_have_value("40")
    page.keyboard.press("Escape")
    _titular(page, "Casa")
    page.get_by_role("button", name="Editar metas").click()
    expect(page.get_by_role("heading", name="Definir metas da casa")).to_be_visible()


def test_horizonte_do_investidor_pelo_chip_de_metas(page: Page):
    page.goto("/metas")
    _titular(page, "Marina")
    chip = page.get_by_role("button", name=re.compile("Horizonte: 10 a 20 anos"))
    expect(chip).to_be_visible()
    chip.click()
    expect(page.get_by_role("heading", name="Horizonte e objetivo de Marina")).to_be_visible()
    page.get_by_label("Por quanto tempo esse dinheiro fica investido?").select_option("mais-de-20")
    page.get_by_label("O que você busca na renda variável?").select_option("renda")
    page.get_by_role("button", name="Salvar", exact=True).click()
    expect(_aviso(page)).to_contain_text("Horizonte e objetivo salvos.")
    expect(page.get_by_role("button", name=re.compile("Horizonte: mais de 20 anos · renda passiva"))).to_be_visible()

    page.get_by_role("button", name=re.compile("Horizonte: mais de 20 anos")).click()
    page.get_by_role("button", name="Usar o da casa").click()
    expect(_aviso(page)).to_contain_text("voltou a usar o horizonte da casa")
    expect(page.get_by_role("button", name=re.compile("Horizonte: 10 a 20 anos"))).to_be_visible()
    _titular(page, "Casa")


def test_ativo_mostra_a_tese_e_o_acompanhamento(page: Page):
    page.goto("/ativo/WEGE3")
    expect(page.get_by_role("heading", name="Tese de longo prazo")).to_be_visible()
    expect(page.locator("main")).to_contain_text("Núcleo")
    page.locator("main").get_by_role("link", name=re.compile("Completa")).click()
    expect(page.locator("main")).to_contain_text("núcleo para 10 a 20 anos")
    page.locator("a.notice", has_text="Acompanhamento").click()
    expect(page.locator("main")).to_contain_text("tese de pé")


def test_categoria_nova_com_icone(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#categorias")
    page.get_by_role("button", name="Nova categoria").click()
    dialogo = page.locator("#dlg-cat-nova")
    dialogo.get_by_label("Nome").fill("Café E2E")
    dialogo.locator("label[title=coffee]").click()
    dialogo.get_by_role("button", name="Criar categoria").click()
    expect(_aviso(page)).to_contain_text("Categoria Café E2E criada.")
    icone = page.locator("#categorias .set-row-main", has_text="Café E2E").locator("use")
    expect(icone).to_have_attribute("href", "/static/icons.svg#i-coffee")
    page.get_by_role("button", name="Editar a categoria Café E2E").click()
    page.locator("dialog[open]").get_by_role("button", name="Excluir categoria").click()
    expect(_aviso(page)).to_contain_text("Categoria Café E2E excluída.")


# ---------------------------------------------------------------- preferências de interface

def test_modo_discreto_esconde_os_valores_e_fica_guardado(page: Page):
    page.goto("/")
    html = page.locator("html")
    olho = page.get_by_role("button", name="Esconder valores")
    olho.click()
    expect(html).to_have_attribute("data-discreto", "")
    expect(page.locator(".hero-value.money")).to_have_css("filter", re.compile("blur"))
    page.goto("/contas")
    expect(html).to_have_attribute("data-discreto", "")
    page.get_by_role("button", name="Mostrar valores").click()
    expect(html).not_to_have_attribute("data-discreto", "")


def test_menu_recolhido_fica_guardado(page: Page):
    page.goto("/")
    page.get_by_role("button", name="Recolher o menu").click()
    expect(page.locator("html")).to_have_attribute("data-nav", "mini")
    expect(page.locator(".sidebar .nav-text").first).to_be_hidden()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-nav", "mini")
    page.get_by_role("button", name="Abrir o menu").click()
    expect(page.locator(".sidebar .nav-text").first).to_be_visible()


def test_tema_claro_pelas_configuracoes(page: Page):
    page.goto("/configuracoes#aparencia")
    page.locator("#aparencia label", has_text="Claro").click()
    expect(_aviso(page)).to_contain_text("Configurações salvas.")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.locator("#aparencia label", has_text="Escuro").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


# ---------------------------------------------------------------- conectar à IA

def test_copiar_texto_para_a_ia(page: Page):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto("/configuracoes#ia")
    page.get_by_role("button", name="Ver texto").click()
    botao = page.locator("button[data-copy='ia-texto']")
    botao.click()
    expect(botao).to_have_text("Copiado")
    copiado = page.evaluate("() => navigator.clipboard.readText()")
    assert "Nome do servidor: tabimoney" in copiado and "`status`" in copiado
    expect(botao).to_have_text("Copiar texto", timeout=3000)


def test_conectar_e_desconectar_o_claude_desktop(aceitar_confirmacoes: Page):
    page = aceitar_confirmacoes
    page.goto("/configuracoes#ia")
    linha = page.locator(".ia-cliente[data-cliente='claude-desktop']")
    linha.get_by_role("button", name="Conectar", exact=True).click()
    expect(_aviso(page)).to_contain_text("conectado ao Claude Desktop")
    expect(linha.locator(".badge")).to_have_text("Conectado")
    linha.get_by_role("button", name="Desconectar").click()
    expect(_aviso(page)).to_contain_text("desconectado do Claude Desktop")
    expect(linha.locator(".badge")).to_have_count(0)


def test_conectar_a_mao_mostra_o_comando_do_claude_code(page: Page):
    page.goto("/configuracoes#ia")
    linha = page.locator(".ia-cliente[data-cliente='claude-code']")
    linha.get_by_role("button", name="Conectar à mão").click()
    expect(linha.locator("textarea")).to_have_value(re.compile(r"^claude mcp add tabimoney --scope user"))


def test_configuracoes_uma_secao_por_vez_e_ajuda_no_popover(page: Page):
    page.goto("/configuracoes")
    expect(page.locator("#geral")).to_be_visible()
    expect(page.locator("#ia")).to_be_hidden()
    page.locator(".set-nav a", has_text="Conectar à IA").click()
    expect(page.locator("#ia")).to_be_visible()
    expect(page.locator("#geral")).to_be_hidden()
    ajuda = page.locator("#hint-ia")
    expect(ajuda).to_be_hidden()
    page.locator("#ia .hint").click()
    expect(ajuda).to_be_visible()
    expect(ajuda).to_contain_text("sem chave de API")
    page.keyboard.press("Escape")
    expect(ajuda).to_be_hidden()


def test_interruptor_salva_sozinho(page: Page):
    page.goto("/configuracoes#atualizacoes")
    interruptor = page.locator("#update_check")
    antes = interruptor.is_checked()
    interruptor.click()
    expect(_aviso(page)).to_contain_text("Configurações salvas.")
    expect(page.locator("#update_check")).to_be_checked(checked=not antes)
    page.locator("#update_check").click()  # volta como estava
    expect(page.locator("#update_check")).to_be_checked(checked=antes)


def test_sino_lista_as_pendencias(page: Page, base_url):
    page.goto("/")
    page.get_by_role("button", name=re.compile("^Pendências")).click()
    menu = page.locator("#pop-inbox")
    expect(menu).to_be_visible()
    expect(menu).to_contain_text("na conciliação")
    menu.get_by_role("link", name="Ver todas as pendências").click()
    expect(page).to_have_url(base_url + "/conciliacao")
    expect(page.locator("h1")).to_have_text("Pendências")


# ---------------------------------------------------------------- dados em todas as telas

@pytest.mark.parametrize("caminho", PAGINAS)
def test_nenhum_grafico_vazio(page: Page, caminho):
    """O servidor de teste usa os dados da demonstração: todo gráfico tem o que desenhar."""
    page.goto(caminho)
    expect(page.locator(".chart-empty")).to_have_count(0)


def test_ver_demonstracao_pelas_configuracoes(aceitar_confirmacoes: Page, base_url):
    page = aceitar_confirmacoes
    page.goto("/configuracoes")
    page.get_by_role("button", name="Ver demonstração").click()
    faixa = page.locator(".demo-banner")
    expect(faixa).to_contain_text("Demonstração · dados fictícios")
    expect(page.locator("h1")).to_have_text("Olá, Lucas!")
    for caminho in PAGINAS:
        page.goto(caminho)
        expect(faixa).to_be_visible()
        expect(page.locator(".chart-empty")).to_have_count(0)

    page.goto("/configuracoes#titulares")
    page.get_by_role("button", name="Novo titular").click()
    page.locator("form[action='/configuracoes/titulares']").get_by_label("Novo titular").fill("Visitante")
    page.get_by_role("button", name="Adicionar titular").click()
    expect(page.locator(".member-switch")).to_contain_text("Visitante")
    faixa.get_by_role("button", name="Recomeçar").click()
    expect(_aviso(page)).to_contain_text("Demonstração recomeçada")
    expect(page.locator(".member-switch")).not_to_contain_text("Visitante")

    page.get_by_role("button", name="Sincronizar").click()
    expect(_aviso(page)).to_contain_text("Na demonstração, sincronizar fica desligado")

    faixa.get_by_role("button", name="Sair da demo").click()
    expect(page.locator(".demo-banner")).to_have_count(0)
    page.goto("/configuracoes")
    expect(page.get_by_role("button", name="Ver demonstração")).to_be_visible()


# ---------------------------------------------------------------- celular

@pytest.mark.parametrize("caminho", PAGINAS)
def test_celular_sem_rolagem_horizontal(page: Page, caminho):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(caminho)
    largura = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert largura <= 1, f"{caminho} passa {largura}px da largura do celular"


def test_celular_tem_a_barra_de_abas(page: Page, base_url):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/")
    expect(page.locator(".sidebar")).to_be_hidden()
    barra = page.locator("nav.tabbar")
    expect(barra).to_be_visible()
    barra.get_by_role("link", name="Gastos").click()
    expect(page).to_have_url(base_url + "/contas")
    barra.get_by_role("button", name="Mais opções").click()
    page.locator("#pop-more").get_by_role("link", name=re.compile("Configurações")).click()
    expect(page).to_have_url(base_url + "/configuracoes")
