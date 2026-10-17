"""Relatório exportado em HTML: período, máscara, contas iguais às das telas, parcelas, recorrentes e a rota."""
from __future__ import annotations

import re
from datetime import date

import pytest

from app.services import analytics, budgets, relatorio, spending


def _mes(hoje: date, atras: int) -> str:
    ano, mes = hoje.year, hoje.month - atras
    while mes <= 0:
        ano, mes = ano - 1, mes + 12
    return f"{ano:04d}-{mes:02d}"


# ---------------------------------------------------------------- período

@pytest.mark.parametrize("tipo, ref, inicio, fim, titulo", [
    ("mes", "2026-08", "2026-08-01", "2026-08-31", "Agosto de 2026"),
    ("mes", "2024-02", "2024-02-01", "2024-02-29", "Fevereiro de 2024"),
    ("trimestre", "2026-T3", "2026-07-01", "2026-09-30", "3º trimestre de 2026"),
    ("trimestre", "2026-11", "2026-10-01", "2026-12-31", "4º trimestre de 2026"),
    ("ano", "2025", "2025-01-01", "2025-12-31", "2025"),
    ("ano", "2025-06", "2025-01-01", "2025-12-31", "2025"),
])
def test_periodos(tipo, ref, inicio, fim, titulo):
    p = relatorio.periodo(tipo, ref)
    assert (p.inicio.isoformat(), p.fim.isoformat(), p.titulo) == (inicio, fim, titulo)


def test_periodo_anterior_atravessa_o_ano():
    assert relatorio.periodo("mes", "2026-01").anterior().ref == "2025-12"
    assert relatorio.periodo("trimestre", "2026-T1").anterior(2).ref == "2025-T3"
    assert relatorio.periodo("ano", "2026").anterior().ref == "2025"
    assert relatorio.nome_arquivo(relatorio.periodo("trimestre", "2026-T3")) == "Tabimoney-2026-T3.html"


@pytest.mark.parametrize("tipo, ref", [("mes", "2026-13"), ("mes", "agosto"), ("trimestre", "2026-T5"), ("semana", None)])
def test_periodo_invalido(tipo, ref):
    with pytest.raises(ValueError):
        relatorio.periodo(tipo, ref)


# ---------------------------------------------------------------- máscara

@pytest.mark.parametrize("descricao, categoria, esperado", [
    ("Pix enviado|Marina Souza", "Pix e transferências", "Pix enviado · M•••a S•••a"),
    ("Pix - Elisangela (faxineira)", "Faxina", "Pix - E•••a (f•••a)"),
    ("TED para XP Investimentos", "Investimentos", "TED para XP Investimentos"),
    ("Transferência para Ana", "Transferência própria", "Transferência para A•••a"),
    ("iFood *Restaurante", "Alimentação", "iFood *Restaurante"),
    ("PIX CPF 123.456.789-09 JOAO", "Outros", "PIX CPF ••• J•••O"),
])
def test_mascara_nomes_de_pessoas_e_documentos(descricao, categoria, esperado):
    assert relatorio.mascarar_descricao(descricao, categoria) == esperado


@pytest.mark.parametrize("conta, esperado", [
    ("Nubank Cartão ••••7730", "Nubank Cartão ••30"),
    ("Itaú ••••1190 · Marina", "Itaú ••90 · Marina"),
    ("Conta 12345-6", "Conta ••45-6"),
    ("Nubank / NuInvest", "Nubank / NuInvest"),
])
def test_mascara_numero_de_conta(conta, esperado):
    assert relatorio.mascarar_conta(conta) == esperado


# ---------------------------------------------------------------- parcelas e recorrentes

@pytest.mark.parametrize("descricao, esperado", [
    ("Magazine Luiza 3/10", (3, 10)), ("Azul - passagem aérea (parcela 2/5)", (2, 5)), ("LOJA PARC 01/12", (1, 12)),
    ("COMPRA 12/08", None), ("Netflix", None), ("Loja 0/3", None),
])
def test_parcela(descricao, esperado):
    assert relatorio.parcela(descricao) == esperado


def _tx(dia: str, descricao: str, cents: int, categoria: str = "Compras", conta: str = "Cartão", tipo: str = "CREDIT"):
    return {"id": 0, "transaction_date": dia, "description": descricao, "amount_cents": cents, "category": categoria,
            "account_name": conta, "account_type": tipo}


def test_parcelas_projetam_so_o_que_falta_depois_do_periodo():
    p = relatorio.periodo("mes", "2026-08")
    transacoes = [
        _tx("2026-07-11", "Azul 1/5", -41356), _tx("2026-08-11", "Azul 2/5", -41356),
        _tx("2026-08-20", "Centauro 3/3", -26984),          # última: nada a projetar
        _tx("2026-03-02", "Loja Antiga 2/10", -5000),       # parou de aparecer: compra quitada ou cancelada
        _tx("2026-09-11", "Azul 3/5", -41356),              # depois do período: não conta
        _tx("2026-08-05", "Conta 05/08", -1000, tipo="BANK"),  # na conta corrente é data, não parcela
    ]
    r = relatorio._parcelas(transacoes, p, mascarar=False)
    assert [(i["nome"], i["parcela"], i["restantes"]) for i in r["itens"]] == [("Azul", "2/5", 3)]
    assert [m["mes"] for m in r["meses"]] == ["2026-09", "2026-10", "2026-11"]
    assert r["total"] == 3 * 41356 and r["proximo"] == 41356


def test_recorrentes_pegam_conta_fixa_e_ignoram_gasto_variavel():
    p = relatorio.periodo("mes", "2026-08")
    transacoes = []
    for mes, luz in (("05", 18000), ("06", 21000), ("07", 24500), ("08", 19900)):
        transacoes += [
            _tx(f"2026-{mes}-02", "Netflix.com", -5590, "Assinaturas"),
            _tx(f"2026-{mes}-08", "Enel Energia", -luz, "Casa", "Conta", "BANK"),
            _tx(f"2026-{mes}-10", "Restaurante", -(3000 if mes != "07" else 12000), "Alimentação"),  # varia demais
        ]
        transacoes += [_tx(f"2026-{mes}-{d:02d}", "Uber", -1500, "Transporte") for d in (3, 9, 15)]  # várias por mês
    transacoes.append(_tx("2026-08-20", "Curso 2/6", -9900, "Educação"))  # parcela não é assinatura
    r = relatorio._recorrentes(transacoes, p, mascarar=False)
    assert sorted(i["nome"] for i in r["itens"]) == ["Enel Energia", "Netflix.com"]
    assert r["assinaturas"] == 5590 and r["anual"] == r["mensal"] * 12


# ---------------------------------------------------------------- montagem com a base

def test_contas_do_relatorio_batem_com_o_fluxo_do_app(dados_exemplo):
    mes = _mes(dados_exemplo, 2)
    d = relatorio.montar("mes", mes)
    fluxo = {r["m"]: r for r in analytics.cash_flow(analytics.cash_transactions() + analytics.Book(None).yield_entries(),
                                                    months=None)}[mes]
    assert (d["receitas"], d["gastos"], d["sobra"]) == (fluxo["in"], fluxo["out"], fluxo["net"])
    assert sum(c["valor"] for c in d["categorias"]) == d["gastos"]
    # pagamento de fatura (os dois lados) fica de fora e é contado só uma vez
    assert d["internos"] == {"valor": 150000, "vezes": 2}
    # o estorno abate a categoria
    alimentacao = next(c for c in d["categorias"] if c["nome"] == "Alimentação")
    assert alimentacao["valor"] == 4590 + 200 + 3890 - 3890
    # 6 meses de base completos? Só os que a base cobre (4 antes deste)
    assert d["base"]["n"] == 4 and "4 meses anteriores" in d["base"]["rotulo"]


def test_resumo_explica_a_diferenca_com_as_categorias(dados_exemplo):
    d = relatorio.montar("mes", _mes(dados_exemplo, 1))
    assert d["resumo"] and d["resumo"][0].startswith("Os gastos somaram")
    assert any(f.startswith("Sobraram") or f.startswith("As despesas passaram") for f in d["resumo"])


def test_periodo_em_andamento_compara_ate_o_mesmo_dia(dados_exemplo):
    d = relatorio.montar("mes")
    assert d["em_andamento"] and "(até o mesmo dia)" in d["base"]["rotulo"]
    assert d["ritmo"]["ate"] == dados_exemplo.day


def test_trimestre_traz_mes_a_mes_e_orcamento_somado(dados_exemplo):
    budgets.save_budget("Mercado", ["Mercado"], 30000)
    d = relatorio.montar("ano", _mes(dados_exemplo, 3))
    assert d["ritmo"] is None and d["mensal"]
    meta = d["orcamento"]["itens"][0]
    meses = len([m for m in d["mensal"]])
    assert meta["limite"] == 30000 * meses and meta["fechados"] <= meses


def test_sem_lancamentos_explica(client):
    with pytest.raises(ValueError, match="Ainda não há lançamentos"):
        relatorio.montar("mes")


def test_periodo_futuro_recusado(dados_exemplo):
    with pytest.raises(ValueError, match="ainda não começou"):
        relatorio.montar("ano", str(dados_exemplo.year + 1))


# ---------------------------------------------------------------- HTML

def test_html_abre_sozinho_e_mascara(dados_exemplo):
    d = relatorio.montar("mes", _mes(dados_exemplo, 1))
    html = relatorio.renderizar(d, nonce="abc")
    assert not re.search(r'(src|href)="(https?:)?//', html)  # nada da internet
    assert "data:font/woff2;base64," in html and "data:image/png;base64," in html
    assert '<symbol id="i-utensils"' in html  # ícone da categoria embutido
    assert "Maria" not in html and "M•••a" in html and "••0001" not in html and "••01" in html
    assert ' style="' not in html and '<script nonce="abc">' in html and '<style nonce="abc">' in html
    sem_mascara = relatorio.renderizar(relatorio.montar("mes", _mes(dados_exemplo, 1), mascarar=False, extrato=False))
    assert "Maria" in sem_mascara and 'id="extrato"' not in sem_mascara


def test_extrato_traz_todos_os_lancamentos_do_periodo(dados_exemplo):
    d = relatorio.montar("mes", _mes(dados_exemplo, 1))
    linhas = [t for g in d["extrato"] for t in g["linhas"]]
    assert len(linhas) == d["extrato_total"] == 8
    assert [g["nome"] for g in d["extrato"]][-2:] == ["Receitas", "Movimentações internas"]


# ---------------------------------------------------------------- rota

def test_rota_abre_com_csp_propria_e_baixa_com_nome(client, dados_exemplo):
    mes = _mes(dados_exemplo, 1)
    r = client.get(f"/contas/relatorio?periodo=mes&ref={mes}")
    assert r.status_code == 200 and "content-disposition" not in r.headers
    csp = r.headers["content-security-policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp and f'<script nonce="{nonce}">' in r.text
    assert "M•••a" in r.text  # sem o formulário, mascara por padrão
    baixado = client.get(f"/contas/relatorio?periodo=trimestre&ref={mes}&enviado=1&baixar=1")
    assert baixado.headers["content-disposition"].startswith('attachment; filename="Tabimoney-')
    assert "Maria" in baixado.text and 'id="extrato"' not in baixado.text  # caixas desmarcadas no formulário


def test_rota_com_periodo_invalido_volta_para_gastos(client, dados_exemplo):
    r = client.get("/contas/relatorio?periodo=mes&ref=2026-13", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/contas")


def test_gastos_tem_o_botao_e_o_dialogo(client, dados_exemplo):
    html = client.get("/contas").text
    assert 'data-dialog="dlg-relatorio"' in html and 'action="/contas/relatorio"' in html


def test_categoria_nova_ganha_icone_no_relatorio(dados_exemplo):
    spending.create_category("Pet", icon="paw-print")
    ids = [t["id"] for t in analytics.cash_transactions() if t["description"] == "Uber"]
    spending.set_category(ids, "Pet")
    hoje = dados_exemplo
    html = relatorio.renderizar(relatorio.montar("mes", _mes(hoje, 3)))
    assert '<symbol id="i-paw-print"' in html


def test_todo_icone_do_template_vai_embutido():
    """Ícone citado no template e fora do sprite some do relatório sem erro nenhum (aconteceu com os selos do orçamento)."""
    from pathlib import Path

    texto = (Path(relatorio.TEMPLATES) / "relatorio_export.html").read_text(encoding="utf-8")
    citados = set(re.findall(r"ic\('([\w-]+)'", texto))
    for trecho in re.findall(r"\{'ok': '[\w-]+', 'risco': '[\w-]+', 'estourou': '[\w-]+'\}", texto):
        citados |= set(re.findall(r": '([\w-]+)'", trecho)) - {"No limite", "Atenção", "Estourou"}
    sprite = (Path(relatorio.TEMPLATES).parent / "static" / "icons.svg").read_text(encoding="utf-8")
    assert citados and citados <= relatorio.ICONES_FIXOS, citados - relatorio.ICONES_FIXOS
    assert all(f'id="i-{nome}"' in sprite for nome in relatorio.ICONES_FIXOS)
