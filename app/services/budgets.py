"""Metas de gastos (orçamento mensal por grupo de categorias) e as recomendações orçamentárias do agente.

Uma meta agrupa uma ou mais categorias de gasto com um limite mensal. Cada categoria pertence a no máximo
uma meta, para o total não contar o mesmo gasto duas vezes; `["*"]` é a meta de gasto total do mês.
O gasto segue a mesma regra de Conta e cartão: saídas menos estornos, sem movimentos internos.

No mês corrente, a projeção é o ritmo até hoje levado ao mês inteiro. Isso avisa cedo quando uma meta
vai estourar, antes de estourar de fato.
"""
from __future__ import annotations

import calendar
import json
import math
from datetime import date, timedelta
from typing import Any

from app.db import rows, transaction
from app.services import spending
from app.services.formatting import brl

TOTAL = "*"
ACTIONS = ("criar", "ajustar", "manter", "remover", "economizar")
# Grupos sugeridos quando o usuário ainda não tem metas: categorias parecidas juntas, poucas metas para cuidar.
SUGGESTED_GROUPS = [
    ("Casa e contas", ["Casa", "Impostos e taxas"]),
    ("Mercado", ["Mercado"]),
    ("Alimentação fora", ["Alimentação"]),
    ("Transporte", ["Transporte"]),
    ("Saúde", ["Saúde"]),
    ("Compras", ["Compras"]),
    ("Lazer e viagens", ["Lazer", "Viagem"]),
    ("Assinaturas", ["Assinaturas"]),
    ("Educação", ["Educação"]),
    ("Pix e outros", ["Pix e transferências", "Outros"]),
]


class BudgetError(ValueError):
    pass


def _round_up(cents: float, step: int = 5000) -> int:
    """Arredonda para cima em múltiplos de R$ 50: meta redonda e com folga pequena."""
    return max(int(math.ceil(cents / step) * step), step)


# ---------------------------------------------------------------- cadastro

def budgets() -> list[dict[str, Any]]:
    data = [dict(r) for r in rows("SELECT * FROM budget ORDER BY monthly_limit_cents DESC, name")]
    for b in data:
        b["categories"] = json.loads(b["categories"])
        b["is_total"] = b["categories"] == [TOTAL]
    return data


def save_budget(name: str, categories: list[str], limit_cents: int, alert_pct: float = 0.8,
                author: str = "usuario", note: str | None = None, budget_id: int | None = None) -> dict[str, Any]:
    name = " ".join((name or "").split())[:60]
    if not name:
        raise BudgetError("Dê um nome para a meta (ex.: Alimentação fora).")
    if limit_cents is None or limit_cents <= 0:
        raise BudgetError("O limite mensal precisa ser maior que zero.")
    if not 0.3 <= alert_pct <= 1:
        raise BudgetError("O aviso precisa disparar entre 30% e 100% do limite.")
    cats = [TOTAL] if TOTAL in categories else sorted({spending.clean_category(c) for c in categories if c and c.strip()})
    if not cats:
        raise BudgetError("Escolha ao menos uma categoria.")
    internal = set(cats) & spending.INTERNAL_CATEGORIES
    if internal:
        raise BudgetError(f"{', '.join(sorted(internal))} não é gasto (é movimento interno); não entra em meta.")
    if cats != [TOTAL]:
        for other in budgets():
            if other["id"] == budget_id or other["is_total"] or other["name"].casefold() == name.casefold():
                continue
            clash = set(cats) & set(other["categories"])
            if clash:
                raise BudgetError(f"{', '.join(sorted(clash))} já está na meta \"{other['name']}\".")
    with transaction() as connection:
        existing = connection.execute(
            "SELECT id FROM budget WHERE id = ? OR name = ? COLLATE NOCASE", (budget_id or -1, name)
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE budget SET name = ?, categories = ?, monthly_limit_cents = ?, alert_pct = ?, author = ?, "
                "note = COALESCE(?, note), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, json.dumps(cats, ensure_ascii=False), int(limit_cents), alert_pct, author, note, existing[0]),
            )
            saved_id = int(existing[0])
        else:
            saved_id = int(connection.execute(
                "INSERT INTO budget(name, categories, monthly_limit_cents, alert_pct, author, note) VALUES (?, ?, ?, ?, ?, ?)",
                (name, json.dumps(cats, ensure_ascii=False), int(limit_cents), alert_pct, author, note),
            ).lastrowid)
    return {"id": saved_id, "name": name, "categories": cats, "monthly_limit": limit_cents / 100}


def delete_budget(budget_id: int | None = None, name: str | None = None) -> int:
    with transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM budget WHERE id = ? OR name = ? COLLATE NOCASE", (budget_id or -1, name or "")
        )
        return cursor.rowcount


# ---------------------------------------------------------------- acompanhamento

def _spent(table: dict[str, dict[str, int]], categories: list[str], month: str) -> int:
    if categories == [TOTAL]:
        return sum(by_month.get(month, 0) for by_month in table.values())
    return sum(table.get(c, {}).get(month, 0) for c in categories)


def status(transactions: list[dict[str, Any]], today: date | None = None, history_months: int = 6) -> dict[str, Any]:
    """Mês corrente contra cada meta, com projeção e quanto ainda cabe por dia; histórico dos meses fechados."""
    today = today or date.today()
    current = today.strftime("%Y-%m")
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = days_in_month - today.day + 1  # hoje ainda conta
    closed = spending._months(date(today.year, today.month, 1) - timedelta(days=1), history_months)
    table = spending.monthly_by_category(transactions, closed + [current])
    items = []
    covered: set[str] = set()
    for b in budgets():
        spent = _spent(table, b["categories"], current)
        limit = b["monthly_limit_cents"]
        # antes do 5º dia o ritmo engana (uma compra grande vira projeção absurda): usa o maior entre o gasto e a média
        history = [_spent(table, b["categories"], m) for m in closed]
        average = sum(history[-3:]) / 3 if history else 0
        projected = spent * days_in_month / today.day if today.day >= 5 else max(spent, average)
        state = "estourou" if spent > limit else "risco" if projected > limit or spent >= limit * b["alert_pct"] else "ok"
        if not b["is_total"]:
            covered.update(b["categories"])
        items.append({
            **b, "spent": spent, "limit": limit, "pct": spent / limit, "projected": int(projected),
            "projected_pct": projected / limit, "remaining": limit - spent,
            "per_day": max(limit - spent, 0) // days_left if days_left else 0, "state": state,
            "history": [{"m": m, "spent": s, "hit": s <= limit} for m, s in zip(closed, history)],
            # meses sem gasto nenhum não contam (a meta talvez nem existisse)
            "hit_rate": sum(1 for s in history if s and s <= limit) / len([s for s in history if s]) if any(history) else None,
            "avg3": int(average),
        })
    uncovered = sorted(
        ({"category": c, "spent": months.get(current, 0), "avg3": int(sum(months.get(m, 0) for m in closed[-3:]) / 3)}
         for c, months in table.items() if c not in covered and (months.get(current, 0) or any(months.get(m) for m in closed[-3:]))),
        key=lambda x: -(x["spent"] or x["avg3"]),
    )
    parts = [i for i in items if not i["is_total"]]
    total_item = next((i for i in items if i["is_total"]), None)
    total_limit = total_item["limit"] if total_item else sum(i["limit"] for i in parts)
    total_spent = total_item["spent"] if total_item else sum(i["spent"] for i in parts)
    all_spent = _spent(table, [TOTAL], current)
    return {
        "month": current, "day": today.day, "days_in_month": days_in_month, "days_left": days_left,
        "items": sorted(items, key=lambda i: ({"estourou": 0, "risco": 1, "ok": 2}[i["state"]], -i["pct"])),
        "uncovered": uncovered, "total_limit": total_limit, "total_spent": total_spent, "all_spent": all_spent,
        "total_pct": total_spent / total_limit if total_limit else None,
        "per_day": max(total_limit - total_spent, 0) // days_left if total_limit and days_left else None,
        "at_risk": sum(1 for i in items if i["state"] != "ok"),
        "coverage": (sum(i["spent"] for i in parts) / all_spent) if all_spent and parts else None,
    }


def suggestions(transactions: list[dict[str, Any]], today: date | None = None) -> list[dict[str, Any]]:
    """Metas sugeridas pela média dos 3 últimos meses fechados, nos grupos padrão (só o que tem gasto)."""
    today = today or date.today()
    closed = spending._months(date(today.year, today.month, 1) - timedelta(days=1), 3)
    table = spending.monthly_by_category(transactions, closed)
    taken = {c for b in budgets() for c in b["categories"]}
    output = []
    grouped = {c for _, cats in SUGGESTED_GROUPS for c in cats}
    extra = [c for c in table if c not in grouped]  # categorias criadas pelo usuário
    groups = SUGGESTED_GROUPS + ([("Outros gastos", extra)] if extra else [])
    for name, cats in groups:
        cats = [c for c in cats if c not in taken]
        average = sum(table.get(c, {}).get(m, 0) for c in cats for m in closed) / 3
        if average < 2000:  # abaixo de R$ 20/mês não vale uma meta
            continue
        output.append({"name": name, "categories": cats, "avg3": int(average), "limit": _round_up(average)})
    return sorted(output, key=lambda s: -s["avg3"])


def create_suggested(transactions: list[dict[str, Any]]) -> int:
    created = 0
    for s in suggestions(transactions):
        save_budget(s["name"], s["categories"], s["limit"], note="Sugerida pela média dos últimos 3 meses")
        created += 1
    return created


# ---------------------------------------------------------------- recomendações do agente

def import_advice(payload: Any, default_author: str = "agente") -> dict[str, int]:
    """Grava as recomendações orçamentárias de um mês (formato em docs/agente-financeiro.md, seção 6)."""
    if not isinstance(payload, dict):
        raise BudgetError("Esperado um objeto JSON com period, title e items.")
    period = str(payload.get("period") or "").strip()
    if len(period) != 7 or period[4] != "-" or not (period[:4] + period[5:]).isdigit():
        raise BudgetError("period deve ser o mês analisado no formato AAAA-MM.")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise BudgetError("Informe title.")
    author = str(payload.get("author") or default_author)[:40]
    items = []
    for i, raw in enumerate(payload.get("items") or [], start=1):
        where = f"items[{i}]"
        if not isinstance(raw, dict):
            raise BudgetError(f"{where}: esperado um objeto.")
        action = str(raw.get("action") or "").strip().lower()
        if action not in ACTIONS:
            raise BudgetError(f"{where}: action deve ser {', '.join(ACTIONS)}.")
        name = " ".join(str(raw.get("budget") or "").split())[:60] or None
        cats = raw.get("categories")
        if cats is not None and (not isinstance(cats, list) or not all(isinstance(c, str) for c in cats)):
            raise BudgetError(f"{where}: categories deve ser uma lista de nomes de categoria.")
        if action in ("criar", "ajustar", "manter", "remover") and not name:
            raise BudgetError(f"{where}: informe budget (nome da meta).")
        if action == "criar" and not cats:
            raise BudgetError(f"{where}: meta nova precisa de categories.")
        suggested = raw.get("suggested_limit")
        if action in ("criar", "ajustar") and (suggested is None or float(suggested) <= 0):
            raise BudgetError(f"{where}: informe suggested_limit (em reais) maior que zero.")
        priority = raw.get("priority")
        if priority is not None and int(priority) not in (1, 2, 3):
            raise BudgetError(f"{where}: priority vai de 1 (alta) a 3 (baixa).")

        def cents(value: Any) -> int | None:
            return int(round(float(value) * 100)) if value is not None else None

        items.append((action, name, json.dumps(cats, ensure_ascii=False) if cats else None, cents(raw.get("current_limit")),
                      cents(suggested), cents(raw.get("expected_monthly_savings")),
                      int(priority) if priority is not None else None, str(raw.get("rationale") or "")[:3000] or None))
    with transaction() as connection:
        connection.execute("DELETE FROM budget_advice_set WHERE period = ? AND author = ?", (period, author))
        set_id = connection.execute(
            "INSERT INTO budget_advice_set(period, title, summary, body_md, expected_monthly_savings_cents, author, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (period, title[:200], str(payload.get("summary") or "")[:3000] or None,
             str(payload.get("body_md") or "")[:200_000] or None,
             int(round(float(payload["expected_monthly_savings"]) * 100)) if payload.get("expected_monthly_savings") is not None else None,
             author, str(payload.get("model") or "")[:80] or None),
        ).lastrowid
        for position, item in enumerate(items):
            connection.execute(
                "INSERT INTO budget_advice_item(set_id, action, budget_name, categories, current_limit_cents, "
                "suggested_limit_cents, expected_monthly_savings_cents, priority, rationale, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (set_id, *item, position),
            )
    return {"set_id": int(set_id), "items": len(items)}


def latest_advice(set_id: int | None = None) -> dict[str, Any] | None:
    found = rows("SELECT * FROM budget_advice_set WHERE id = ?", (set_id,)) if set_id else rows(
        "SELECT * FROM budget_advice_set ORDER BY created_at DESC, id DESC LIMIT 1"
    )
    if not found:
        return None
    data = dict(found[0])
    data["items"] = []
    current = {b["name"].casefold(): b for b in budgets()}
    for r in rows("SELECT * FROM budget_advice_item WHERE set_id = ? ORDER BY COALESCE(priority, 9), position", (data["id"],)):
        item = dict(r)
        item["categories"] = json.loads(item["categories"]) if item["categories"] else None
        existing = current.get((item["budget_name"] or "").casefold())
        # aplicável: cria/ajusta/remove uma meta e ainda não foi aplicado (ou a meta mudou depois)
        item["applicable"] = item["action"] in ("criar", "ajustar", "remover") and not item["applied_at"] and not (
            item["action"] == "remover" and not existing
        )
        item["existing_limit"] = existing["monthly_limit_cents"] if existing else None
        # "antes": depois de aplicada, a meta atual já é a sugerida; mostra o limite de quando o agente analisou
        item["before"] = item["current_limit_cents"] if item["applied_at"] else (item["existing_limit"] or item["current_limit_cents"])
        item["show_categories"] = bool(item["categories"]) and item["categories"] != [item["budget_name"]]
        data["items"].append(item)
    return data


def advice_history() -> list[dict[str, Any]]:
    return [dict(r) for r in rows(
        "SELECT s.id, s.period, s.title, s.author, s.created_at, s.expected_monthly_savings_cents, "
        "(SELECT COUNT(*) FROM budget_advice_item i WHERE i.set_id = s.id) AS items "
        "FROM budget_advice_set s ORDER BY s.created_at DESC, s.id DESC"
    )]


def apply_advice(item_id: int) -> str:
    """Aplica uma sugestão do agente: cria, ajusta ou remove a meta. Devolve a mensagem para o usuário."""
    found = rows("SELECT * FROM budget_advice_item WHERE id = ?", (item_id,))
    if not found:
        raise BudgetError("Sugestão não encontrada.")
    item = dict(found[0])
    if item["applied_at"]:
        raise BudgetError("Essa sugestão já foi aplicada.")
    name = item["budget_name"]
    existing = next((b for b in budgets() if b["name"].casefold() == (name or "").casefold()), None)
    if item["action"] == "remover":
        delete_budget(name=name)
        message = f"Meta \"{name}\" removida."
    elif item["action"] in ("criar", "ajustar"):
        cats = json.loads(item["categories"]) if item["categories"] else (existing["categories"] if existing else None)
        if not cats:
            raise BudgetError(f"A sugestão não diz quais categorias a meta \"{name}\" cobre.")
        save_budget(name, cats, item["suggested_limit_cents"], existing["alert_pct"] if existing else 0.8,
                    author="agente", note="Aplicada a partir da recomendação do agente", budget_id=existing["id"] if existing else None)
        message = f"Meta \"{name}\" agora é de {brl(item['suggested_limit_cents'])} por mês."
    else:
        raise BudgetError("Essa sugestão é só uma orientação; não há meta para aplicar.")
    with transaction() as connection:
        connection.execute("UPDATE budget_advice_item SET applied_at = CURRENT_TIMESTAMP WHERE id = ?", (item_id,))
    return message
