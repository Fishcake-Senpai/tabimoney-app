"""A interface do revamp 0.14: formatação, ícones de categoria, barra do topo, aparência e as abas novas.

Guia de design: docs/superpowers/specs/2026-09-30-revamp-ui.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import db
from app.services import categories, formatting, spending

from .conftest import avisos, csrf


# ---------------------------------------------------------------- formatação

def test_valor_heroi_separa_os_centavos():
    html = str(formatting.brl_hero(22601851))
    assert html == 'R$ 226.018<span class="cents">,51</span>'
    assert str(formatting.brl_hero(-500)).startswith("−R$ 5")
    assert str(formatting.brl_hero(None)) == "—"


@pytest.mark.parametrize("n, esperado", [(0, "0 metas"), (1, "1 meta"), (5, "5 metas"), (None, "0 metas")])
def test_plural(n, esperado):
    assert formatting.plural(n, "meta", "metas") == esperado


def test_plural_sem_forma_plural_acrescenta_s():
    assert formatting.plural(2, "conta") == "2 contas"


def test_dia_relativo():
    hoje = date(2026, 9, 30)
    assert formatting.day_label("2026-09-30", hoje) == "Hoje"
    assert formatting.day_label("2026-09-29", hoje) == "Ontem"
    assert formatting.day_label("2026-09-26", hoje) == "sáb, 26/09"
    assert formatting.day_label("2025-12-31", hoje) == "31/12/2025"


def test_tempo_desde_a_ultima_sincronizacao():
    agora = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    assert formatting.ago("2026-09-30 11:59:30", agora) == "agora"
    assert formatting.ago("2026-09-30 11:55:00", agora) == "há 5 min"
    assert formatting.ago("2026-09-30 09:00:00", agora) == "há 3 h"
    assert formatting.ago("2026-09-28 12:00:00", agora) == "há 2 dias"
    assert formatting.ago(None) == ""


def test_titulo_do_lancamento_e_mes_por_extenso():
    assert formatting.tx_title("Pix enviado|Marina") == "Pix enviado · Marina"
    assert formatting.month_long("2026-09", date(2026, 9, 30)) == "setembro"
    assert formatting.month_long("2025-12", date(2026, 9, 30)) == "dezembro de 2025"
    assert formatting.long_date("2026-09-30") == "quarta, 30 de setembro"


# ---------------------------------------------------------------- ícones de categoria

def test_icone_da_categoria():
    assert categories.category_icon("Mercado") == "shopping-cart"
    assert categories.category_icon("Pet shop do Totó") == "paw-print"  # pela palavra do nome
    assert categories.category_icon("Coisa nova") == "circle-dashed"
    assert categories.category_icon("Coisa nova", "gift") == "gift"
    assert categories.category_icon("Coisa nova", "nao-existe") == "circle-dashed"


def test_todo_icone_usado_existe_no_sprite():
    from pathlib import Path

    sprite = (Path(__file__).resolve().parents[1] / "app" / "static" / "icons.svg").read_text(encoding="utf-8")
    usados = set(categories.CATEGORY_ICONS.values()) | set(categories.CATEGORY_ICON_CHOICES)
    usados |= {icon for _, icon in categories.CATEGORY_ICON_HINTS}
    faltando = [nome for nome in usados if f'id="i-{nome}"' not in sprite]
    assert not faltando, f"rode packaging/icones.py com estes nomes: {faltando}"


def test_criar_categoria_com_icone_e_trocar(client):
    token = csrf(client)
    client.post("/contas/categorias", data={"csrf_token": token, "name": "Delivery", "icon": "gift"})
    assert spending.custom_icons() == {"Delivery": "gift"}
    r = client.post("/contas/categorias/icone", data={"csrf_token": token, "name": "Delivery", "icon": "coffee"})
    assert ("success", "Ícone de Delivery trocado.") in avisos(r.text)
    assert spending.custom_icons() == {"Delivery": "coffee"}
    r = client.post("/contas/categorias/icone", data={"csrf_token": token, "name": "Mercado", "icon": "coffee"})
    assert avisos(r.text)[0][0] == "error"  # as padrão têm ícone fixo


def test_icone_escolhido_aparece_nas_configuracoes(client):
    spending.create_category("Delivery", icon="coffee")
    assert "#i-coffee" in client.get("/configuracoes").text


# ---------------------------------------------------------------- barra do topo

def test_barra_do_topo_tem_titular_olho_sincronizar_sino_e_importar(client):
    from app.services import household

    household.add_member("Ana")
    pagina = client.get("/").text
    assert 'class="member-switch"' in pagina
    assert "data-discreet-toggle" in pagina
    assert 'action="/sincronizar"' in pagina
    assert 'popovertarget="pop-inbox"' in pagina
    assert 'href="/importar"' in pagina


def test_sino_conta_as_sugestoes_da_ia_e_leva_para_elas(client):
    from app import demo

    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    pagina = client.get("/").text
    assert "sugestões da IA para o orçamento" in pagina
    assert "avisos nos seus ativos" in pagina
    assert "divergência na conciliação" in pagina
    assert demo.path().exists()


def test_sincronizar_na_demo_fica_desligado(client):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    r = client.post("/sincronizar", data={"csrf_token": csrf(client), "back": "/contas"})
    assert r.url.path == "/contas"
    assert any(tipo == "warning" and "sincronizar fica desligado" in msg for tipo, msg in avisos(r.text))


def test_sincronizar_sem_banco_conectado_so_atualiza_o_mercado(client):
    r = client.post("/sincronizar", data={"csrf_token": csrf(client)})
    fontes = [row["source"] for row in db.rows("SELECT source FROM sync_run")]
    assert fontes and all("Pluggy" not in f for f in fontes)
    assert avisos(r.text)  # sem rede nos testes: o mercado avisa o que houve, sem quebrar a página


def test_sincronizar_recusa_voltar_para_fora_do_app(client):
    r = client.post("/sincronizar", data={"csrf_token": csrf(client), "back": "//exemplo.com"}, follow_redirects=False)
    assert r.headers["location"] == "/"


# ---------------------------------------------------------------- aparência

def test_tema_e_modo_discreto_salvos_nas_configuracoes(client):
    token = csrf(client)
    assert 'data-tema-padrao="escuro"' in client.get("/").text
    client.post("/configuracoes", data={"csrf_token": token, "secao": "tema", "ui_theme": "claro"})
    client.post("/configuracoes", data={"csrf_token": token, "secao": "discreto", "ui_discreet": "on"})
    pagina = client.get("/").text
    assert 'data-tema-padrao="claro"' in pagina and 'data-discreto-padrao="1"' in pagina
    client.post("/configuracoes", data={"csrf_token": token, "secao": "tema", "ui_theme": "roxo"})
    assert db.get_setting("ui_theme") == "claro"  # valor desconhecido é ignorado
    client.post("/configuracoes", data={"csrf_token": token, "secao": "discreto"})
    assert db.get_setting("ui_discreet") == "0"


def test_salvar_a_aparencia_nao_mexe_no_resto(client):
    db.set_setting("daily_quotes_enabled", "1")
    client.post("/configuracoes", data={"csrf_token": csrf(client), "secao": "tema", "ui_theme": "sistema"})
    assert db.get_setting("daily_quotes_enabled") == "1"


# ---------------------------------------------------------------- telas

def test_boas_vindas_na_base_vazia(client):
    pagina = client.get("/").text
    assert "Bem-vindo ao Tabimoney" in pagina and "Importe um extrato" in pagina and "Conecte a IA" in pagina


def test_inicio_com_dados_mostra_o_patrimonio_e_os_ultimos_lancamentos(client, dados_exemplo):
    pagina = client.get("/").text
    assert "Patrimônio" in pagina and "Últimos lançamentos" in pagina
    assert "Pagamento de fatura" not in pagina.split("Últimos lançamentos", 1)[1].split("Pede sua atenção", 1)[0]


def test_gastos_troca_de_mes(client, dados_exemplo):
    anterior = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    pagina = client.get(f"/contas?mes={anterior}").text
    assert f"Gasto em {formatting.month_long(anterior)}" in pagina
    # mês inválido cai no corrente
    assert f"Gasto em {formatting.month_long(date.today().isoformat())}" in client.get("/contas?mes=1999-01").text


def test_lancamentos_abrem_no_painel_com_a_regra_ali(client, dados_exemplo):
    pagina = client.get("/contas/lancamentos").text
    assert 'id="dlg-tx"' in pagina and "Usar sempre para" in pagina
    assert pagina.count("data-tx=") >= 20


def test_trocar_categoria_pelo_painel_volta_para_os_lancamentos(client, dados_exemplo):
    tx = db.rows("SELECT id FROM cash_transaction WHERE description = 'iFood' LIMIT 1")[0][0]
    r = client.post("/contas/categoria", data={"csrf_token": csrf(client), "transaction_id": tx, "category": "Lazer",
                                               "back": "/contas/lancamentos"})
    assert r.url.path == "/contas/lancamentos"
    assert ("success", "Categoria alterada para Lazer.") in avisos(r.text)


def test_orcamento_cria_meta_pelo_dialogo_e_volta_para_a_aba(client, dados_exemplo):
    r = client.post("/orcamento", data={"csrf_token": csrf(client), "name": "Comida", "limit": "900",
                                        "categories": ["Alimentação"]})
    assert r.url.path == "/contas/orcamento"
    assert 'id="dlg-nova-meta"' in r.text and "Comida" in r.text


def test_categorias_e_regras_moraram_para_as_configuracoes(client):
    token = csrf(client)
    r = client.post("/contas/regras", data={"csrf_token": token, "pattern": "PADARIA", "category": "Alimentação"})
    assert r.url.path == "/configuracoes" and "“PADARIA” → Alimentação" in r.text
    r = client.post("/contas/categorias", data={"csrf_token": token, "name": "Academia"})
    assert r.url.path == "/configuracoes" and "Academia" in r.text


def test_backup_mora_nas_configuracoes(client):
    pagina = client.get("/configuracoes").text
    assert 'action="/backup"' in pagina and 'action="/restaurar"' in pagina
    assert 'action="/backup"' not in client.get("/importar").text


def test_investimentos_resumo_e_abas(client):
    from app import demo

    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    pagina = client.get("/investimentos").text
    for aba in ("/carteira", "/renda-fixa", "/previdencia", "/rendimentos", "/metas"):
        assert f'href="{aba}"' in pagina
    assert "Onde aportar" in pagina and "Alocação" in pagina
    assert demo.path().exists()


def test_carteira_visao_de_fundamentos(client):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    assert 'id="positions"' in client.get("/carteira").text
    pagina = client.get("/carteira?vista=fundamentos").text
    assert 'id="positions"' not in pagina and 'id="avisos"' in pagina


@pytest.mark.parametrize("aba", ["visao", "fundamentos", "resultados", "analises", "eventos", "qualquer"])
def test_abas_do_ativo(client, aba):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    resposta = client.get(f"/ativo/EGIE3?aba={aba}")
    assert resposta.status_code == 200 and 'aria-current="page"' in resposta.text


def test_pendencias_reune_conciliacao_e_avisos(client):
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    pagina = client.get("/conciliacao").text
    assert "<h1>Pendências</h1>" in pagina and 'id="avisos"' in pagina and "Transferências sem par" in pagina


def test_menu_tem_quatro_destinos(client, dados_exemplo):
    pagina = client.get("/").text
    principal = pagina.split('aria-label="Principal"', 1)[1].split("</nav>", 1)[0]
    assert [rotulo for rotulo in ("Início", "Gastos", "Investimentos", "Sugestões") if rotulo in principal] == [
        "Início", "Gastos", "Investimentos", "Sugestões"]
    assert principal.count("<a ") == 4


def test_nenhuma_pagina_usa_style_inline(client, dados_exemplo):
    """A CSP (style-src 'self') bloqueia style="": larguras e cores saem de classe ou do app.js."""
    from fastapi.routing import APIRoute

    from app.main import app

    for rota in [r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
                 and not r.path.startswith("/csv/") and r.path != "/favicon.ico"]:
        assert ' style="' not in client.get(rota).text, rota


def test_todo_link_interno_de_toda_pagina_abre(client):
    """Clicar em qualquer link (menu, abas, cards, linhas) nunca leva a 404 nem a erro.

    Pega, por exemplo, o href montado como texto num macro, que o Jinja escapava ("/%22/previdencia%22").
    """
    import re
    from html import unescape

    from fastapi.routing import APIRoute

    from app.main import app

    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    paginas = [r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
               and not r.path.startswith("/csv/") and r.path not in {"/favicon.ico", "/importacoes"}]
    paginas += ["/ativo/EGIE3", "/contas/gastos/Mercado", "/carteira?vista=fundamentos"]
    links: dict[str, str] = {}
    for pagina in paginas:
        html = client.get(pagina).text
        assert "href=&#34;" not in html and "href=&quot;" not in html, f"{pagina}: href com aspas escapadas"
        for href in re.findall(r'<a [^>]*href="([^"]*)"', html):
            href = unescape(href).split("#")[0]
            if href.startswith("/") and not href.startswith("//") and not href.startswith("/static/"):
                links.setdefault(href, pagina)
    assert len(links) > 40
    quebrados = []
    for href, origem in sorted(links.items()):
        resposta = client.get(href, follow_redirects=True)
        if resposta.status_code != 200:
            quebrados.append(f"{href} (em {origem}): {resposta.status_code}")
    assert not quebrados, "\n".join(quebrados)
