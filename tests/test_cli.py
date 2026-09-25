"""Linha de comando (financas.bat / Tabimoney cli) e o ponto de entrada do executável."""
from __future__ import annotations

import json

import pytest

from app import __version__, cli, launch


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_versao(capsys):
    launch.main(["--versao"])
    assert capsys.readouterr().out.strip() == __version__


def test_cli_pelo_ponto_de_entrada(capsys):
    launch.main(["cli", "gastos", "categorias"])
    saida = _json(capsys)
    assert "Alimentação" in saida["categorias"]
    assert "Pagamento de fatura" in saida["internas_fora_de_receita_e_despesa"]


def test_resumo_de_gastos(capsys, dados_exemplo):
    cli.main(["gastos", "resumo", "--meses", "3"])
    saida = _json(capsys)
    assert any(c["categoria"] == "Alimentação" for c in saida["categorias"])


def test_lancamento_em_dolar_traz_o_valor_original(capsys, dados_exemplo):
    cli.main(["gastos", "listar", "--categoria", "Assinaturas", "--limite", "1"])
    lancamento = _json(capsys)["lancamentos"][0]
    assert lancamento["valor"] == -114.0
    assert (lancamento["moeda_original"], lancamento["valor_original"]) == ("USD", -21.0)


def test_criar_e_excluir_categoria(capsys, dados_exemplo):
    cli.main(["gastos", "criar-categoria", "Pets"])
    assert _json(capsys)["criada"] is True
    cli.main(["gastos", "criar-categoria", "pets"])
    assert _json(capsys)["criada"] is False
    cli.main(["gastos", "excluir-categoria", "Pets"])
    assert _json(capsys)["excluida"] is True


def test_excluir_categoria_em_uso_sem_destino_sai_com_codigo_2(capsys, dados_exemplo):
    cli.main(["gastos", "criar-categoria", "Delivery"])
    capsys.readouterr()
    from app.services import analytics, spending

    spending.set_category([analytics.cash_transactions()[0]["id"]], "Delivery")
    with pytest.raises(SystemExit) as saida:
        cli.main(["gastos", "excluir-categoria", "Delivery"])
    assert saida.value.code == 2
    assert "em uso" in _json(capsys)["erro"]
