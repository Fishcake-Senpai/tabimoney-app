"""Gastos por categoria: correções do usuário/agente e tendência mês a mês.

A categoria automática (`category`) é regravada a cada sincronização. A correção fica em `user_category`
(um lançamento) ou em `category_rule` (todos os lançamentos cuja descrição contém um texto), e vale por cima
da automática — assim o erro da API não volta na próxima sincronização.
"""
from __future__ import annotations

import calendar
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from app.db import rows, transaction
from app.services.categories import INCOME_CATEGORIES, INTERNAL_CATEGORIES
from app.services.formatting import brl_compact, month_label

BASE_CATEGORIES = [
    "Alimentação", "Mercado", "Transporte", "Casa", "Saúde", "Educação", "Compras", "Assinaturas", "Lazer",
    "Viagem", "Impostos e taxas", "Pix e transferências", "Outros",
    "Salário", "Proventos", "Rendimentos",
    "Investimentos", "Pagamento de fatura", "Transferência própria",
]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def clean_category(value: str) -> str:
    """Aceita 'alimentacao', 'ALIMENTAÇÃO' etc. e devolve a grafia de uma categoria existente."""
    text = " ".join((value or "").split())[:40]
    if not text:
        raise ValueError("Informe a categoria.")
    wanted = normalize(text)
    for category in known_categories():
        if normalize(category) == wanted:
            return category
    return text[:1].upper() + text[1:]


def known_categories() -> list[str]:
    used = [r[0] for r in rows(
        "SELECT DISTINCT COALESCE(user_category, category) FROM cash_transaction WHERE COALESCE(user_category, category) IS NOT NULL"
    )]
    used += [r[0] for r in rows("SELECT DISTINCT category FROM category_rule")]
    used += [r[0] for r in rows("SELECT name FROM category WHERE deleted_at IS NULL")]
    seen: dict[str, str] = {}
    for category in BASE_CATEGORIES + sorted(used, key=normalize):
        seen.setdefault(normalize(category), category)
    return list(seen.values())


# ---------------------------------------------------------------- categorias próprias

class CategoryInUse(ValueError):
    """Excluir uma categoria com lançamentos, regras ou metas exige dizer para onde eles vão."""

    def __init__(self, name: str, usage: dict[str, Any]) -> None:
        self.usage = usage
        parts = [f"{usage['manual']} lançamento(s)", f"{len(usage['rules'])} regra(s)", f"{len(usage['budgets'])} meta(s)"]
        super().__init__(f"A categoria {name} está em uso ({', '.join(parts)}). Escolha para onde mover antes de excluir.")


AUTOMATIC = "automatica"  # destino da exclusão: cada lançamento volta à sua categoria automática
_BASE_KEYS = {normalize(c) for c in BASE_CATEGORIES}


def is_base(name: str) -> bool:
    return normalize(name) in _BASE_KEYS


def _register(connection, name: str, author: str) -> bool:
    """Garante a categoria na tabela; reativa se tinha sido excluída (e aí a restauração deixa de valer)."""
    key = normalize(name)
    if key in _BASE_KEYS:
        return False
    row = connection.execute("SELECT id, deleted_at FROM category WHERE name_key = ?", (key,)).fetchone()
    if row is None:
        connection.execute("INSERT INTO category(name, name_key, author) VALUES (?, ?, ?)", (name, key, author))
        return True
    if row["deleted_at"]:
        connection.execute(
            "UPDATE category SET name = ?, author = ?, deleted_at = NULL, moved_to = NULL, undo = NULL, "
            "created_at = CURRENT_TIMESTAMP WHERE id = ?", (name, author, row["id"]),
        )
        return True
    return False


def create_category(name: str, author: str = "usuario") -> dict[str, Any]:
    """Idempotente: criar uma que já existe (em qualquer grafia) devolve a existente com criada=False."""
    text = " ".join((name or "").split())
    if len(text) < 2 or len(text) > 40:
        raise ValueError("O nome da categoria precisa ter de 2 a 40 caracteres.")
    if text == "*" or normalize(text).startswith("automatica") or normalize(text) == "n/a":
        raise ValueError(f"'{text}' é um nome reservado.")
    wanted = normalize(text)
    existing = next((c for c in known_categories() if normalize(c) == wanted), None)
    if existing:
        return {"categoria": existing, "criada": False, "padrao": is_base(existing)}
    value = text[:1].upper() + text[1:]
    with transaction() as connection:
        _register(connection, value, author)
    return {"categoria": value, "criada": True, "padrao": False}


def _budget_rows(connection=None) -> list[dict[str, Any]]:
    data = connection.execute("SELECT * FROM budget").fetchall() if connection else rows("SELECT * FROM budget")
    output = []
    for r in data:
        b = dict(r)
        b["cats"] = json.loads(b["categories"])
        output.append(b)
    return output


def category_usage(name: str, connection=None) -> dict[str, Any]:
    """O que depende da categoria: lançamentos corrigidos à mão, regras e metas."""
    key = normalize(name)
    query = (lambda sql, params=(): connection.execute(sql, params).fetchall()) if connection else rows
    manual = [r["id"] for r in query("SELECT id, user_category FROM cash_transaction WHERE user_category IS NOT NULL")
              if normalize(r["user_category"]) == key]
    rule_list = [dict(r) for r in query("SELECT * FROM category_rule") if normalize(r["category"]) == key]
    budgets = [b for b in _budget_rows(connection) if any(normalize(c) == key for c in b["cats"])]
    return {"manual": len(manual), "manual_ids": manual, "rules": rule_list, "budgets": budgets,
            "in_use": bool(manual or rule_list or budgets)}


def categories_overview(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Todas as categorias com quanto uso têm, para a tela de gerenciar categorias."""
    effective = Counter(t["category"] or "Outros" for t in transactions)
    custom = {r["name_key"]: dict(r) for r in rows("SELECT * FROM category WHERE deleted_at IS NULL")}
    output = []
    for name in known_categories():
        usage = category_usage(name)
        row = custom.get(normalize(name))
        output.append({
            "name": name, "base": is_base(name), "author": row["author"] if row else None,
            "transactions": effective.get(name, 0), "manual": usage["manual"],
            "rules": len(usage["rules"]), "budgets": [b["name"] for b in usage["budgets"]], "in_use": usage["in_use"],
        })
    return output


def deleted_categories() -> list[dict[str, Any]]:
    data = [dict(r) for r in rows("SELECT name, moved_to, deleted_at, undo FROM category WHERE deleted_at IS NOT NULL "
                                  "ORDER BY deleted_at DESC")]
    for d in data:
        undo = json.loads(d.pop("undo") or "{}")
        d["moved"] = len(undo.get("transactions", [])) + len(undo.get("rules_updated", [])) + len(undo.get("rules_deleted", []))
    return data


def delete_category(name: str, destination: str | None = None, author: str = "usuario") -> dict[str, Any]:
    """Exclui uma categoria própria. Com lançamentos, regras ou metas atrelados, exige o destino deles:
    outra categoria (ex.: Outros) ou AUTOMATIC. Tudo numa transação; o que mudou fica guardado para restaurar."""
    if is_base(name):
        raise ValueError(f"{name} é uma categoria padrão e não pode ser excluída.")
    key = normalize(name)
    current = next((c for c in known_categories() if normalize(c) == key), None)
    if current is None:
        gone = rows("SELECT name FROM category WHERE name_key = ? AND deleted_at IS NOT NULL", (key,))
        if gone:
            return {"categoria": gone[0]["name"], "excluida": False, "motivo": "já estava excluída"}
        raise ValueError(f"A categoria {name} não existe.")
    automatic = destination is not None and normalize(destination) in {AUTOMATIC, "automatica", ""}
    target = None
    if destination is not None and not automatic:
        target = next((c for c in known_categories() if normalize(c) == normalize(destination)), None)
        if target is None:
            raise ValueError(f"A categoria de destino {destination} não existe.")
        if normalize(target) == key:
            raise ValueError("O destino precisa ser outra categoria.")

    with transaction() as connection:
        usage = category_usage(current, connection)
        if usage["in_use"] and destination is None:
            raise CategoryInUse(current, usage)
        undo: dict[str, Any] = {"transactions": usage["manual_ids"], "rules_updated": [], "rules_deleted": [],
                                "budgets_updated": [], "budgets_deleted": []}
        if usage["manual_ids"]:
            ids = usage["manual_ids"]
            connection.execute(
                f"UPDATE cash_transaction SET user_category = ? WHERE id IN ({','.join('?' * len(ids))})", (target, *ids)
            )
        for rule in usage["rules"]:
            if target:
                connection.execute("UPDATE category_rule SET category = ? WHERE id = ?", (target, rule["id"]))
                undo["rules_updated"].append(rule["id"])
            else:
                connection.execute("DELETE FROM category_rule WHERE id = ?", (rule["id"],))
                undo["rules_deleted"].append(rule)
        # cada categoria entra em uma meta só: se o destino já está em outra meta, esta só perde a categoria
        taken = {normalize(c): b["id"] for b in _budget_rows(connection) for c in b["cats"]}
        for b in usage["budgets"]:
            cats = [c for c in b["cats"] if normalize(c) != key]
            added = bool(target) and taken.get(normalize(target), b["id"]) == b["id"] and target not in cats
            if added:
                cats.append(target)
            if cats:
                connection.execute("UPDATE budget SET categories = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                   (json.dumps(sorted(cats), ensure_ascii=False), b["id"]))
                undo["budgets_updated"].append({"id": b["id"], "added": target if added else None})
            else:
                connection.execute("DELETE FROM budget WHERE id = ?", (b["id"],))
                undo["budgets_deleted"].append({k: v for k, v in b.items() if k != "cats"})
        connection.execute(
            "INSERT INTO category(name, name_key, author) VALUES (?, ?, ?) ON CONFLICT(name_key) DO NOTHING",
            (current, key, author),
        )
        connection.execute(
            "UPDATE category SET deleted_at = CURRENT_TIMESTAMP, moved_to = ?, undo = ? WHERE name_key = ?",
            (target if target else (AUTOMATIC if automatic else None), json.dumps(undo, ensure_ascii=False), key),
        )
    return {
        "categoria": current, "excluida": True, "destino": target or ("automática" if automatic else None),
        "lancamentos": len(usage["manual_ids"]), "regras_movidas": len(undo["rules_updated"]),
        "regras_removidas": len(undo["rules_deleted"]), "metas_ajustadas": len(undo["budgets_updated"]),
        "metas_removidas": [b["name"] for b in undo["budgets_deleted"]],
    }


def restore_category(name: str) -> dict[str, Any]:
    """Desfaz a exclusão: devolve à categoria o que ainda está onde a exclusão deixou (o que o usuário mudou
    depois fica como está)."""
    key = normalize(name)
    row = rows("SELECT * FROM category WHERE name_key = ?", (key,))
    if not row or not row[0]["deleted_at"]:
        return {"categoria": name, "restaurada": False, "motivo": "não está excluída"}
    row = dict(row[0])
    undo = json.loads(row["undo"] or "{}")
    moved_to = row["moved_to"] if row["moved_to"] != AUTOMATIC else None
    restored = {"lancamentos": 0, "regras": 0, "metas": 0}
    with transaction() as connection:
        ids = undo.get("transactions", [])
        if ids:
            marks = ",".join("?" * len(ids))
            cursor = connection.execute(
                f"UPDATE cash_transaction SET user_category = ? WHERE id IN ({marks}) AND user_category IS ?",
                (row["name"], *ids, moved_to),
            )
            restored["lancamentos"] = cursor.rowcount
        for rule_id in undo.get("rules_updated", []):
            restored["regras"] += connection.execute(
                "UPDATE category_rule SET category = ? WHERE id = ? AND category IS ?", (row["name"], rule_id, moved_to)
            ).rowcount
        for rule in undo.get("rules_deleted", []):
            # UNIQUE não pega account_name NULL no SQLite; confere à mão para não duplicar a regra
            if connection.execute("SELECT 1 FROM category_rule WHERE pattern = ? AND account_name IS ?",
                                  (rule["pattern"], rule.get("account_name"))).fetchone():
                continue
            restored["regras"] += connection.execute(
                "INSERT INTO category_rule(pattern, category, account_name, author, note) VALUES (?, ?, ?, ?, ?)",
                (rule["pattern"], row["name"], rule.get("account_name"), rule.get("author") or "usuario", rule.get("note")),
            ).rowcount
        taken = {normalize(c) for b in _budget_rows(connection) for c in b["cats"]}
        if key not in taken:
            for item in undo.get("budgets_updated", []):
                b = next((x for x in _budget_rows(connection) if x["id"] == item["id"]), None)
                if b is None:
                    continue
                cats = [c for c in b["cats"] if not item["added"] or c != item["added"]] + [row["name"]]
                connection.execute("UPDATE budget SET categories = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                   (json.dumps(sorted(cats), ensure_ascii=False), b["id"]))
                restored["metas"] += 1
            for b in undo.get("budgets_deleted", []):
                restored["metas"] += connection.execute(
                    "INSERT INTO budget(name, categories, monthly_limit_cents, alert_pct, author, note) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO NOTHING",
                    (b["name"], json.dumps([row["name"]], ensure_ascii=False), b["monthly_limit_cents"], b["alert_pct"],
                     b["author"], b.get("note")),
                ).rowcount
        connection.execute("UPDATE category SET deleted_at = NULL, moved_to = NULL, undo = NULL WHERE id = ?", (row["id"],))
    return {"categoria": row["name"], "restaurada": True, **restored}


def rules() -> list[dict[str, Any]]:
    return [dict(r) for r in rows("SELECT * FROM category_rule ORDER BY LENGTH(pattern) DESC, id")]


def apply_overrides(transactions: list[dict[str, Any]]) -> None:
    """Categoria efetiva: manual > regra do usuário (a mais específica) > automática."""
    compiled = [(normalize(r["pattern"]), r) for r in rules()]
    for t in transactions:
        t["auto_category"] = t["category"]
        t["category_source"] = "auto"
        if t.get("user_category"):
            t["category"] = t["user_category"]
            t["category_source"] = "manual"
            continue
        text = normalize(t["description"])
        for pattern, rule in compiled:
            if pattern and pattern in text and (not rule["account_name"] or rule["account_name"] == t["account_name"]):
                t["category"] = rule["category"]
                t["category_source"] = "regra"
                t["rule_id"] = rule["id"]
                break


def set_category(transaction_ids: list[int], category: str | None, author: str = "usuario") -> int:
    """Corrige lançamentos. Categoria vazia devolve o lançamento à categoria automática; um nome novo cria a
    categoria."""
    value = clean_category(category) if category and category.strip() else None
    ids = [int(i) for i in transaction_ids]
    if not ids:
        return 0
    with transaction() as connection:
        if value:
            _register(connection, value, author)
        cursor = connection.execute(
            f"UPDATE cash_transaction SET user_category = ? WHERE id IN ({','.join('?' * len(ids))})", (value, *ids)
        )
        return cursor.rowcount


def add_rule(pattern: str, category: str, account_name: str | None = None, author: str = "usuario",
             note: str | None = None) -> dict[str, Any]:
    text = " ".join((pattern or "").split())
    if len(text) < 3:
        raise ValueError("O texto da regra precisa ter ao menos 3 caracteres.")
    value = clean_category(category)
    with transaction() as connection:
        _register(connection, value, author)
        connection.execute(
            "INSERT INTO category_rule(pattern, category, account_name, author, note) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(pattern, account_name) DO UPDATE SET category = excluded.category, author = excluded.author, "
            "note = excluded.note",
            (text, value, account_name or None, author, note),
        )
    matched = sum(1 for r in rows("SELECT description FROM cash_transaction") if normalize(text) in normalize(r[0]))
    return {"pattern": text, "category": value, "matches": matched}


def delete_rule(rule_id: int) -> None:
    with transaction() as connection:
        connection.execute("DELETE FROM category_rule WHERE id = ?", (int(rule_id),))


# ---------------------------------------------------------------- tendência

def _spend_kind(t: dict[str, Any]) -> bool:
    """Entra no gasto: saída, ou estorno (entrada fora das categorias de receita), nunca movimento interno."""
    category = t["category"] or "Outros"
    if category in INTERNAL_CATEGORIES:
        return False
    return t["amount_cents"] < 0 or not (t["account_type"] == "BANK" and category in INCOME_CATEGORIES)


def monthly_by_category(transactions: list[dict[str, Any]], months: list[str]) -> dict[str, dict[str, int]]:
    wanted = set(months)
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in transactions:
        month = t["transaction_date"][:7]
        if month in wanted and _spend_kind(t):
            table[t["category"] or "Outros"][month] -= int(t["amount_cents"])
    return table


def _months(end: date, count: int) -> list[str]:
    year, month = end.year, end.month
    output = []
    for _ in range(count):
        output.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(output))


def category_trends(transactions: list[dict[str, Any]], today: date | None = None, window: int = 6) -> dict[str, Any]:
    """Gasto por categoria nos últimos meses e o que mudou.

    'Mudou' compara o último mês fechado com a média dos 3 meses fechados anteriores. O mês corrente aparece
    na tabela, com o ritmo projetado para o mês inteiro, mas não entra na comparação (está incompleto).
    """
    today = today or date.today()
    current = today.strftime("%Y-%m")
    closed = _months(date(today.year, today.month, 1) - timedelta(days=1), window)
    months = closed + [current]
    table = monthly_by_category(transactions, months)
    last, base = closed[-1], closed[-4:-1]
    days_in_month = ((date(today.year + today.month // 12, today.month % 12 + 1, 1)) - date(today.year, today.month, 1)).days
    pace = days_in_month / today.day
    categories = []
    for category, by_month in table.items():
        values = [by_month.get(m, 0) for m in months]
        if not any(v > 0 for v in values):
            continue
        average = sum(by_month.get(m, 0) for m in base) / len(base)
        last_value = by_month.get(last, 0)
        previous_3 = sum(by_month.get(m, 0) for m in closed[-6:-3])
        recent_3 = sum(by_month.get(m, 0) for m in closed[-3:])
        categories.append({
            "category": category, "values": values, "last": last_value, "avg3": int(average),
            "delta": int(last_value - average), "delta_pct": (last_value - average) / average if average > 0 else None,
            "recent3": recent_3, "previous3": previous_3,
            "trend_pct": (recent_3 - previous_3) / previous_3 if previous_3 > 0 else None,
            "current": by_month.get(current, 0), "current_pace": int(by_month.get(current, 0) * pace),
            "total": sum(values[:-1]),
        })
    categories.sort(key=lambda c: -c["total"])
    changes = sorted(
        (c for c in categories if abs(c["delta"]) >= 5000 and (c["delta_pct"] is None or abs(c["delta_pct"]) >= 0.15)),
        key=lambda c: -abs(c["delta"]),
    )
    for change in changes:
        drivers = [
            t for t in transactions
            if t["transaction_date"][:7] == last and (t["category"] or "Outros") == change["category"] and _spend_kind(t)
        ]
        change["drivers"] = sorted(drivers, key=lambda t: t["amount_cents"])[:3]
    totals = [sum(c["values"][i] for c in categories) for i in range(len(months))]
    return {"months": months, "last": last, "base": base, "categories": categories, "changes": changes[:8],
            "totals": totals, "pace": pace}


# ---------------------------------------------------------------- detalhe de uma categoria

WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
WEEKDAYS_LONG = ["às segundas", "às terças", "às quartas", "às quintas", "às sextas", "aos sábados", "aos domingos"]


def merchant(description: str) -> str:
    """Estabelecimento a partir da descrição: último trecho de 'Pix|Nome' e sem o '3/10' da parcela."""
    text = (description or "").split("|")[-1].strip()
    return re.sub(r"\s*\(?\d{1,2}/\d{1,2}\)?$", "", text) or "Sem descrição"


def _cumulative(items: list[dict[str, Any]], month: str, days: int, upto: int | None = None) -> list[int | None]:
    """Gasto acumulado dia a dia no mês; dias além do mês de referência caem no último dia."""
    daily = [0] * days
    for t in items:
        if t["transaction_date"][:7] == month:
            daily[min(int(t["transaction_date"][8:10]), days) - 1] -= int(t["amount_cents"])
    output: list[int | None] = []
    acc = 0
    for index, value in enumerate(daily):
        acc += value
        output.append(acc if upto is None or index < upto else None)
    return output


def _change(new: float, old: float) -> float | None:
    return (new - old) / old if old > 0 else None


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def category_detail(transactions: list[dict[str, Any]], category: str, today: date | None = None) -> dict[str, Any] | None:
    """Tudo o que a página de uma categoria mostra: série mensal, ritmo do mês, estabelecimentos, dia da semana
    e observações. A janela de análise são os últimos 12 meses fechados mais o mês corrente."""
    items = [t for t in transactions if (t["category"] or "Outros") == category and _spend_kind(t)]
    if not items:
        return None
    today = today or date.today()
    current = today.strftime("%Y-%m")
    first = min(t["transaction_date"][:7] for t in transactions)
    count = (today.year - int(first[:4])) * 12 + today.month - int(first[5:7]) + 1
    months = _months(today, max(1, min(count, 24)))
    closed = months[:-1]
    window = closed[-12:]
    since = (window[0] if window else current) + "-01"
    by_month: dict[str, int] = defaultdict(int)
    for t in items:
        by_month[t["transaction_date"][:7]] -= int(t["amount_cents"])

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    pace = days_in_month / today.day
    spent_now = by_month.get(current, 0)
    avg12 = sum(by_month.get(m, 0) for m in window) / len(window) if window else 0
    last = closed[-1] if closed else None
    base = closed[-4:-1]
    avg3 = sum(by_month.get(m, 0) for m in base) / len(base) if base else 0
    recent3 = sum(by_month.get(m, 0) for m in closed[-3:])
    previous3 = sum(by_month.get(m, 0) for m in closed[-6:-3]) if len(closed) >= 6 else 0

    recent = [t for t in items if t["transaction_date"] >= since]
    purchases = [t for t in recent if t["amount_cents"] < 0]
    refunds = sum(int(t["amount_cents"]) for t in recent if t["amount_cents"] > 0)
    spent_window = sum(-int(t["amount_cents"]) for t in recent)
    ranking = sorted(
        ((c, sum(v.values())) for c, v in monthly_by_category(transactions, window + [current]).items()),
        key=lambda item: -item[1],
    )
    all_window = sum(value for _, value in ranking if value > 0)
    rank = next((i + 1 for i, (c, _) in enumerate(ranking) if c == category), None)

    # estabelecimentos
    groups: dict[str, dict[str, Any]] = {}
    for t in recent:
        name = merchant(t["description"])
        g = groups.setdefault(normalize(name), {"names": Counter(), "value": 0, "count": 0, "months": set(), "last": ""})
        g["names"][name] += 1
        g["value"] -= int(t["amount_cents"])
        if t["amount_cents"] < 0:
            g["count"] += 1
        g["months"].add(t["transaction_date"][:7])
        g["last"] = max(g["last"], t["transaction_date"])
    merchants = sorted(
        ({"label": g["names"].most_common(1)[0][0], "value": g["value"], "count": g["count"], "months": len(g["months"]),
          "last": g["last"], "avg": g["value"] // g["count"] if g["count"] else 0}
         for g in groups.values() if g["value"] > 0),
        key=lambda m: -m["value"],
    )
    for m in merchants:
        m["pct"] = m["value"] / spent_window if spent_window > 0 else 0

    # dia da semana (só compras, para o estorno não puxar um dia para baixo)
    weekday_value, weekday_count = [0] * 7, [0] * 7
    for t in purchases:
        wd = date.fromisoformat(t["transaction_date"]).weekday()
        weekday_value[wd] -= int(t["amount_cents"])
        weekday_count[wd] += 1

    # ritmo do mês: acumulado dia a dia contra o mês passado e a média dos 3 últimos meses fechados
    last3 = closed[-3:]
    pace_series = {
        "month": current, "days": days_in_month, "today": today.day,
        "current": _cumulative(items, current, days_in_month, today.day),
        "previous": _cumulative(items, last, days_in_month) if last else [],
        "average": [int(sum(col) / len(last3)) for col in zip(*(_cumulative(items, m, days_in_month) for m in last3))]
        if last3 else [],
    }
    # projeção: o já gasto mais o que costuma sair nos dias que faltam (curva média). A regra de três do
    # mês inteiro inflaria gastos pontuais, como uma mensalidade paga no dia 5.
    average = pace_series["average"]
    projected = spent_now + max(0, average[-1] - average[today.day - 1]) if average else spent_now * pace

    def ticket(month_list: list[str]) -> tuple[float, float]:
        chosen = [t for t in purchases if t["transaction_date"][:7] in month_list]
        value = sum(-int(t["amount_cents"]) for t in chosen)
        return (value / len(chosen) if chosen else 0, len(chosen) / len(month_list) if month_list else 0)

    ticket_recent, freq_recent = ticket(closed[-3:])
    ticket_before, freq_before = ticket(window[:-3])

    insights: list[dict[str, str]] = []

    def note(text: str, kind: str = "") -> None:
        insights.append({"text": text, "tone": kind})

    if today.day >= 5 and avg12 > 0:
        diff = _change(projected, avg12) or 0
        if abs(diff) >= 0.1:
            note(f"No ritmo atual, {month_label(current)} fecha em {brl_compact(int(projected))}, "
                 f"{abs(diff):.0%} {'acima' if diff > 0 else 'abaixo'} da média de 12 meses ({brl_compact(int(avg12))}).",
                 "down" if diff > 0 else "up")
        else:
            note(f"No ritmo atual, {month_label(current)} fecha em {brl_compact(int(projected))}, perto da média de 12 meses.")
    if last and avg3 > 0:
        diff = _change(by_month.get(last, 0), avg3) or 0
        if abs(diff) >= 0.15:
            note(f"{month_label(last)} ficou {abs(diff):.0%} {'acima' if diff > 0 else 'abaixo'} da média dos 3 meses "
                 f"anteriores ({brl_compact(by_month.get(last, 0))} contra {brl_compact(int(avg3))}).",
                 "down" if diff > 0 else "up")
    trend = _change(recent3, previous3)
    if trend is not None and abs(trend) >= 0.15:
        note(f"Tendência: os últimos 3 meses somam {abs(trend):.0%} {'a mais' if trend > 0 else 'a menos'} "
             "que os 3 anteriores.", "down" if trend > 0 else "up")
    if merchants and merchants[0]["pct"] >= 0.2:
        top = merchants[0]
        note(f"{top['label']} concentra {top['pct']:.0%} do gasto em 12 meses: {brl_compact(top['value'])} "
             f"em {top['count']} compra(s), média de {brl_compact(top['avg'])}.")
    recurring = [m for m in merchants if m["months"] >= max(3, len(window) // 2)][:3]
    if recurring:
        names = ", ".join(m["label"] for m in recurring)
        note(f"Presença constante: {names} aparece{'m' if len(recurring) > 1 else ''} em metade ou mais dos meses.")
    if ticket_recent and ticket_before:
        diff = _change(ticket_recent, ticket_before) or 0
        freq_diff = _change(freq_recent, freq_before) or 0
        if abs(diff) >= 0.15 or abs(freq_diff) >= 0.2:
            note(f"Nos últimos 3 meses: {_decimal(freq_recent)} compras por mês, de {brl_compact(int(ticket_recent))} em "
                 f"média (antes, {_decimal(freq_before)} de {brl_compact(int(ticket_before))}).")
    total_purchases = sum(weekday_value)
    if total_purchases > 0 and len(purchases) >= 10:
        wd = max(range(7), key=lambda i: weekday_value[i])
        share = weekday_value[wd] / total_purchases
        if share >= 0.22:
            note(f"Você gasta mais {WEEKDAYS_LONG[wd]}:{share:.0%} do valor, em {weekday_count[wd]} compra(s).")
    if all_window > 0 and spent_window > 0 and rank:
        note(f"É a {rank}ª maior categoria nos últimos 12 meses, com {spent_window / all_window:.0%} dos seus gastos.")
    if refunds > 0:
        note(f"Estornos de {brl_compact(refunds)} nos últimos 12 meses já estão abatidos.")

    return {
        "category": category,
        "months": [{"m": m, "v": by_month.get(m, 0)} for m in months],
        "current": current, "last": last, "spent_now": spent_now, "projected": int(projected), "pace": pace,
        "avg12": int(avg12), "avg3": int(avg3), "last_value": by_month.get(last, 0) if last else 0,
        "last_delta_pct": _change(by_month.get(last, 0), avg3) if last else None,
        "trend_pct": trend, "spent_window": spent_window, "window_months": len(window),
        "share": spent_window / all_window if all_window > 0 else None, "rank": rank,
        "count": len(purchases), "ticket": spent_window // len(purchases) if purchases else 0,
        "merchants": merchants,
        "biggest": sorted(purchases, key=lambda t: t["amount_cents"])[:5],
        "weekday": {"labels": WEEKDAYS, "values": weekday_value, "counts": weekday_count},
        "pace_series": pace_series,
        "insights": insights,
        "transactions": sorted(items, key=lambda t: (t["transaction_date"], t["id"]), reverse=True),
    }
