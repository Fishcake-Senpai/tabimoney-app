"""Regras de gasto que já quebraram uma vez: fatura aberta, moeda estrangeira e a página de categoria."""
from __future__ import annotations

from app.services import analytics, spending
from app.services.sync import _foreign_currency, _signed_amount


def _descricoes():
    return [t["description"] for t in analytics.cash_transactions()]


def test_compra_pendente_do_cartao_entra_nos_gastos(dados_exemplo):
    hoje = dados_exemplo.isoformat()
    pendentes = [t for t in analytics.cash_transactions() if t["status"] == "PENDING"]
    assert [(t["description"], t["transaction_date"]) for t in pendentes] == [("iFood", hoje)]


def test_parcela_futura_e_pendente_da_conta_ficam_fora(dados_exemplo):
    descricoes = _descricoes()
    assert "Loja 2/5" not in descricoes
    assert "Pix pendente" not in descricoes


def test_compra_em_dolar_usa_o_valor_em_reais():
    compra = {"amount": 21.36, "amountInAccountCurrency": 114.45, "currencyCode": "USD", "type": "DEBIT"}
    assert _signed_amount(compra, "CREDIT") == -11445
    assert _foreign_currency(compra, "BRL") == "USD"


def test_compra_em_reais_nao_muda():
    compra = {"amount": 50.0, "currencyCode": "BRL", "type": "DEBIT"}
    assert _signed_amount(compra, "CREDIT") == -5000
    assert _foreign_currency(compra, "BRL") is None


def test_sinal_segue_o_tipo_em_conta_e_cartao():
    assert _signed_amount({"amount": 10, "type": "CREDIT"}, "CREDIT") == 1000   # estorno no cartão
    assert _signed_amount({"amount": -10, "type": "DEBIT"}, "BANK") == -1000
    assert _signed_amount({"amount": 10}, "CREDIT") == -1000                     # sem type: compra no cartão


def test_tendencia_por_categoria(dados_exemplo):
    trends = spending.category_trends(analytics.cash_transactions())
    categorias = {c["category"]: c for c in trends["categories"]}
    assert "Alimentação" in categorias and "Salário" not in categorias and "Pagamento de fatura" not in categorias
    assert categorias["Mercado"]["values"][-2] == 32000  # último mês fechado


def test_detalhe_da_categoria(dados_exemplo):
    detalhe = spending.category_detail(analytics.cash_transactions(), "Alimentação")
    assert detalhe is not None
    assert detalhe["spent_now"] == 5000                  # só a compra pendente de hoje
    assert detalhe["merchants"][0]["label"] == "iFood"
    assert detalhe["insights"]
    assert spending.category_detail(analytics.cash_transactions(), "Não existe") is None


def test_estorno_abate_o_gasto_da_categoria(dados_exemplo):
    detalhe = spending.category_detail(analytics.cash_transactions(), "Alimentação")
    estornos = [t for t in detalhe["transactions"] if t["amount_cents"] > 0]
    assert estornos and estornos[0]["description"] == "Estorno iFood"


def test_estabelecimento_ignora_parcela_e_prefixo_do_pix():
    assert spending.merchant("Loja 3/10") == "Loja"
    assert spending.merchant("Pix enviado|Maria") == "Maria"
