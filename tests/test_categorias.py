"""Categorias próprias: criar é idempotente, excluir em uso exige destino, excluir e restaurar são reversíveis."""
from __future__ import annotations

import pytest

from app.services import analytics, budgets, spending


def _categoria(tid):
    return next(t for t in analytics.cash_transactions() if t["id"] == tid)["category"]


@pytest.fixture
def delivery(dados_exemplo):
    """Categoria Delivery com 2 lançamentos corrigidos à mão, uma regra e uma meta."""
    spending.create_category("Delivery")
    ids = [t["id"] for t in analytics.cash_transactions() if t["description"] == "iFood"][:2]
    spending.set_category(ids, "Delivery")
    spending.add_rule("RAPPI", "Delivery")
    budgets.save_budget("Teste delivery", ["Delivery"], 50000)
    return ids


def test_criar_e_idempotente_em_qualquer_grafia():
    assert spending.create_category("delivery") == {"categoria": "Delivery", "criada": True, "padrao": False}
    assert spending.create_category("  DÉLIVERY ")["criada"] is False
    assert spending.create_category("alimentacao") == {"categoria": "Alimentação", "criada": False, "padrao": True}


@pytest.mark.parametrize("nome", ["*", "x", "Automática", "N/A", "a" * 41])
def test_nomes_reservados_ou_invalidos(nome):
    with pytest.raises(ValueError):
        spending.create_category(nome)


def test_excluir_em_uso_sem_destino_e_bloqueado(delivery):
    with pytest.raises(spending.CategoryInUse) as erro:
        spending.delete_category("Delivery")
    assert erro.value.usage["manual"] == 2
    assert all(_categoria(i) == "Delivery" for i in delivery)


@pytest.mark.parametrize("nome, destino", [("Outros", "Lazer"), ("Delivery", "delivery"), ("Delivery", "Xpto")])
def test_exclusoes_invalidas(delivery, nome, destino):
    with pytest.raises(ValueError):
        spending.delete_category(nome, destino)


def test_excluir_para_outros_move_tudo_e_restaurar_devolve(delivery):
    r = spending.delete_category("Delivery", "Outros")
    assert (r["lancamentos"], r["regras_movidas"], r["metas_ajustadas"]) == (2, 1, 1)
    assert all(_categoria(i) == "Outros" for i in delivery)
    assert next(b for b in budgets.budgets() if b["name"] == "Teste delivery")["categories"] == ["Outros"]
    assert "Delivery" not in spending.known_categories()
    assert spending.delete_category("Delivery", "Outros")["excluida"] is False  # de novo: nada acontece

    spending.restore_category("Delivery")
    assert all(_categoria(i) == "Delivery" for i in delivery)
    assert any(r["pattern"] == "RAPPI" and r["category"] == "Delivery" for r in spending.rules())
    assert next(b for b in budgets.budgets() if b["name"] == "Teste delivery")["categories"] == ["Delivery"]
    assert spending.restore_category("Delivery")["restaurada"] is False


def test_excluir_para_automatica_remove_regra_e_meta_vazia_e_restaura(delivery):
    r = spending.delete_category("Delivery", "automatica")
    assert r["regras_removidas"] == 1 and r["metas_removidas"] == ["Teste delivery"]
    assert all(_categoria(i) == "Alimentação" for i in delivery)
    spending.restore_category("Delivery")
    assert all(_categoria(i) == "Delivery" for i in delivery)
    assert any(b["name"] == "Teste delivery" for b in budgets.budgets())


def test_categoria_sem_uso_exclui_sem_destino():
    spending.create_category("Pets")
    assert spending.delete_category("Pets")["excluida"] is True


def test_recriar_categoria_excluida_nao_ressuscita_os_itens(delivery):
    spending.delete_category("Delivery", "Outros")
    spending.create_category("Delivery")
    assert spending.restore_category("Delivery")["restaurada"] is False
    assert all(_categoria(i) == "Outros" for i in delivery)
