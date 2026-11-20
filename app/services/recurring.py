"""Contas fixas (recorrências) com baixa automática.

Frequências de semanal a anual, ajuste opcional para dia útil no fim de semana, e casamento automático
com o lançamento real importado/sincronizado: o previsto é trocado pelo cobrado, sem contar em dobro.
O estado de cada parcela no mês (pago, pendente, atrasado) é derivado na leitura.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from app.db import rows, transaction
from app.services import spending
from app.services import transactions as tx_service

FREQUENCIES: dict[str, str] = {
    "weekly": "Semanal",
    "biweekly": "Quinzenal",
    "monthly": "Mensal",
    "quarterly": "Trimestral",
    "yearly": "Anual",
}

MATCH_DATE_WINDOW_DAYS = 5
MATCH_AMOUNT_TOLERANCE_PCT = 0.05
MATCH_AMOUNT_TOLERANCE_CENTS = 200  # até R$ 2,00 de variação


def adjust_to_business_day(d: date) -> date:
    """Se cair em sábado ou domingo, move para a segunda-feira seguinte."""
    wd = d.weekday()
    if wd == 5:  # sábado
        return d + timedelta(days=2)
    if wd == 6:  # domingo
        return d + timedelta(days=1)
    return d


def _add_months(year: int, month: int, delta: int, day_of_month: int) -> date:
    total = year * 12 + (month - 1) + delta
    y, m0 = divmod(total, 12)
    m = m0 + 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(day_of_month, last_day))


def occurrences(rec: dict[str, Any], window_start: date, window_end: date) -> list[date]:
    """Gera as datas previstas de uma conta fixa dentro de [window_start, window_end]."""
    start = date.fromisoformat(rec["start_date"])
    end = date.fromisoformat(rec["end_date"]) if rec.get("end_date") else None
    effective_end = min(window_end, end) if end else window_end
    if effective_end < start or effective_end < window_start:
        return []

    freq = rec["frequency"]
    adjust = bool(rec.get("adjust_business_day"))
    day_of_month = int(rec["day_of_month"] or start.day)
    result: list[date] = []

    if freq in ("weekly", "biweekly"):
        step = 7 if freq == "weekly" else 14
        cur = start
        if cur < window_start - timedelta(days=step):
            jumps = (window_start - cur).days // step
            cur = cur + timedelta(days=jumps * step)
        while cur <= effective_end + timedelta(days=2):
            due = adjust_to_business_day(cur) if adjust else cur
            if window_start <= due <= effective_end and cur >= start and (end is None or cur <= end):
                result.append(due)
            cur += timedelta(days=step)
    else:
        step_months = {"monthly": 1, "quarterly": 3, "yearly": 12}[freq]
        # Começa no primeiro mês >= start
        months_diff = (window_start.year - start.year) * 12 + (window_start.month - start.month)
        k = max(0, (months_diff // step_months) - 1)
        while True:
            raw = _add_months(start.year, start.month, k * step_months, day_of_month)
            if raw < start:
                k += 1
                continue
            if end and raw > end:
                break
            due = adjust_to_business_day(raw) if adjust else raw
            if due > effective_end + timedelta(days=2):
                break
            if window_start <= due <= effective_end:
                result.append(due)
            k += 1
    return result


# ---------------------------------------------------------------- CRUD

def list_recurring(member: int | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
    where = ["r.deleted_at IS NULL"]
    params: list[Any] = []
    if not include_inactive:
        where.append("r.active = 1")
    if member is not None:
        where.append("COALESCE(a.member_id, 1) = ?")
        params.append(member)
    data = rows(
        "SELECT r.*, a.account_name, a.account_type, COALESCE(a.member_id, 1) AS member_id "
        "FROM recurring_transaction r JOIN financial_account a ON a.id = r.account_id "
        f"WHERE {' AND '.join(where)} ORDER BY r.active DESC, r.description",
        tuple(params),
    )
    out = []
    for r in data:
        item = dict(r)
        item["adjust_business_day"] = bool(item["adjust_business_day"])
        item["active"] = bool(item["active"])
        item["frequency_label"] = FREQUENCIES.get(item["frequency"], item["frequency"])
        out.append(item)
    return out


def save_recurring(
    *,
    account_id: int | str | None,
    description: str,
    amount_cents: int,
    frequency: str = "monthly",
    start_date: str | None = None,
    day_of_month: int | None = None,
    end_date: str | None = None,
    category: str | None = None,
    adjust_business_day: bool = False,
    match_pattern: str | None = None,
    note: str | None = None,
    active: bool = True,
    recurring_id: int | None = None,
    member: int | None = None,
    author: str = "usuario",
) -> dict[str, Any]:
    """Cria ou atualiza uma conta fixa."""
    if frequency not in FREQUENCIES:
        raise ValueError(f"Frequência inválida: {frequency!r}. Use: {', '.join(FREQUENCIES)}.")
    if int(amount_cents) == 0:
        raise ValueError("O valor da conta fixa não pode ser zero.")
    desc = tx_service._clean_description(description)
    aid = tx_service.resolve_account_id(account_id, member=member)
    iso_start = tx_service._clean_date(start_date or date.today().isoformat())
    iso_end = tx_service._clean_date(end_date) if end_date and end_date.strip() else None
    if iso_end and iso_end < iso_start:
        raise ValueError("A data final precisa ser depois da data inicial.")
    dom = int(day_of_month) if day_of_month else date.fromisoformat(iso_start).day
    if not 1 <= dom <= 31:
        raise ValueError("O dia do mês precisa estar entre 1 e 31.")
    clean_cat = spending.clean_category(category) if category and category.strip() else None
    pattern = " ".join((match_pattern or "").split())[:120] or None
    clean_note = tx_service._clean_note(note)

    with transaction() as conn:
        if clean_cat:
            spending._register(conn, clean_cat, author)
        if recurring_id:
            found = conn.execute(
                "SELECT id FROM recurring_transaction WHERE id = ? AND deleted_at IS NULL",
                (int(recurring_id),),
            ).fetchone()
            if not found:
                raise ValueError("Conta fixa não encontrada.")
            conn.execute(
                "UPDATE recurring_transaction SET account_id = ?, description = ?, amount_cents = ?, "
                "category = ?, frequency = ?, day_of_month = ?, start_date = ?, end_date = ?, "
                "adjust_business_day = ?, active = ?, match_pattern = ?, note = ? WHERE id = ?",
                (
                    aid, desc, int(amount_cents), clean_cat, frequency, dom, iso_start, iso_end,
                    1 if adjust_business_day else 0, 1 if active else 0, pattern, clean_note, int(recurring_id),
                ),
            )
            rid = int(recurring_id)
        else:
            cursor = conn.execute(
                "INSERT INTO recurring_transaction("
                "account_id, description, amount_cents, category, frequency, day_of_month, start_date, end_date, "
                "adjust_business_day, active, match_pattern, note, author"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid, desc, int(amount_cents), clean_cat, frequency, dom, iso_start, iso_end,
                    1 if adjust_business_day else 0, 1 if active else 0, pattern, clean_note, author,
                ),
            )
            rid = int(cursor.lastrowid)

    match_recurring()
    return next(r for r in list_recurring(include_inactive=True) if r["id"] == rid)


def delete_recurring(recurring_id: int) -> dict[str, Any]:
    found = rows(
        "SELECT id, description FROM recurring_transaction WHERE id = ? AND deleted_at IS NULL",
        (int(recurring_id),),
    )
    if not found:
        raise ValueError("Conta fixa não encontrada.")
    with transaction() as conn:
        conn.execute("UPDATE recurring_transaction SET deleted_at = CURRENT_TIMESTAMP, active = 0 WHERE id = ?", (int(recurring_id),))
    return {"id": int(recurring_id), "descricao": found[0]["description"], "excluida": True}


# ---------------------------------------------------------------- baixa automática (matching)

def _amount_matches(expected: int, actual: int) -> bool:
    if (expected < 0) != (actual < 0):
        return False
    diff = abs(abs(expected) - abs(actual))
    return diff <= max(MATCH_AMOUNT_TOLERANCE_CENTS, int(abs(expected) * MATCH_AMOUNT_TOLERANCE_PCT))


def _description_matches(rec: dict[str, Any], tx_desc: str) -> bool:
    needle = spending.normalize(rec.get("match_pattern") or rec["description"])
    hay = spending.normalize(tx_desc)
    if not needle or not hay:
        return False
    if needle in hay or hay in needle:
        return True
    # Compara palavras relevantes (>= 3 letras)
    words = [w for w in needle.split() if len(w) >= 3]
    return bool(words) and all(w in hay for w in words)


def match_recurring(window_start: date | None = None, window_end: date | None = None, today: date | None = None) -> int:
    """Casa lançamentos reais ainda sem vínculo com as ocorrências previstas das contas fixas.
    Quando casa, grava recurring_id e recurring_due_date no lançamento real (sem duplicar)."""
    today = today or date.today()
    w_start = window_start or (today - timedelta(days=45))
    w_end = window_end or (today + timedelta(days=10))
    recs = list_recurring(include_inactive=False)
    if not recs:
        return 0

    # Ocorrências já baixadas no período
    already_settled = {
        (int(r["recurring_id"]), str(r["recurring_due_date"]))
        for r in rows(
            "SELECT recurring_id, recurring_due_date FROM cash_transaction "
            "WHERE recurring_id IS NOT NULL AND recurring_due_date IS NOT NULL AND deleted_at IS NULL"
        )
    }

    # Candidatos reais disponíveis
    tx_start = (w_start - timedelta(days=MATCH_DATE_WINDOW_DAYS)).isoformat()
    tx_end = (w_end + timedelta(days=MATCH_DATE_WINDOW_DAYS)).isoformat()
    candidates = [
        dict(r)
        for r in rows(
            "SELECT t.id, t.account_id, a.account_name, t.transaction_date, t.description, t.amount_cents, t.user_category "
            "FROM cash_transaction t JOIN financial_account a ON a.id = t.account_id "
            "WHERE t.deleted_at IS NULL AND t.is_ignored = 0 AND t.recurring_id IS NULL "
            "AND t.transaction_date BETWEEN ? AND ? ORDER BY t.transaction_date, t.id",
            (tx_start, tx_end),
        )
    ]
    used_tx: set[int] = set()
    matches: list[tuple[int, str, int, str | None]] = []  # (recurring_id, due_iso, tx_id, category_to_apply)

    for rec in recs:
        rid = int(rec["id"])
        for due in occurrences(rec, w_start, w_end):
            due_iso = due.isoformat()
            if (rid, due_iso) in already_settled:
                continue
            best: tuple[int, int, dict[str, Any]] | None = None  # (score, day_gap, tx)
            for tx in candidates:
                tx_id = int(tx["id"])
                if tx_id in used_tx:
                    continue
                if tx["account_id"] != rec["account_id"] and tx["account_name"] != rec["account_name"]:
                    continue
                gap = abs((date.fromisoformat(tx["transaction_date"]) - due).days)
                if gap > MATCH_DATE_WINDOW_DAYS:
                    continue
                if not _amount_matches(int(rec["amount_cents"]), int(tx["amount_cents"])):
                    continue
                desc_ok = _description_matches(rec, tx["description"])
                exact_amt = int(tx["amount_cents"]) == int(rec["amount_cents"])
                if not desc_ok and not (exact_amt and gap <= 3):
                    continue
                # Menor score = melhor casamento (descrição + valor exato + menor distância em dias)
                score = (0 if desc_ok else 10) + (0 if exact_amt else 5) + gap
                if best is None or (score, gap) < (best[0], best[1]):
                    best = (score, gap, tx)
            if best is not None:
                tx = best[2]
                used_tx.add(int(tx["id"]))
                already_settled.add((rid, due_iso))
                cat_apply = rec["category"] if (rec.get("category") and not tx.get("user_category")) else None
                matches.append((rid, due_iso, int(tx["id"]), cat_apply))

    if not matches:
        return 0
    with transaction() as conn:
        for rid, due_iso, tx_id, cat_apply in matches:
            if cat_apply:
                conn.execute(
                    "UPDATE cash_transaction SET recurring_id = ?, recurring_due_date = ?, user_category = ? WHERE id = ?",
                    (rid, due_iso, cat_apply, tx_id),
                )
            else:
                conn.execute(
                    "UPDATE cash_transaction SET recurring_id = ?, recurring_due_date = ? WHERE id = ?",
                    (rid, due_iso, tx_id),
                )
    return len(matches)


def settle_occurrence(recurring_id: int, due_date: str, author: str = "usuario") -> dict[str, Any]:
    """Dá baixa manual em uma ocorrência criando um lançamento manual já vinculado à conta fixa."""
    found = [r for r in list_recurring(include_inactive=True) if r["id"] == int(recurring_id)]
    if not found:
        raise ValueError("Conta fixa não encontrada.")
    rec = found[0]
    due_iso = tx_service._clean_date(due_date)
    existing = rows(
        "SELECT id FROM cash_transaction WHERE recurring_id = ? AND recurring_due_date = ? AND deleted_at IS NULL",
        (int(recurring_id), due_iso),
    )
    if existing:
        raise ValueError("Esta ocorrência já foi baixada.")
    return tx_service.create_transaction(
        account_id=rec["account_id"],
        transaction_date=due_iso,
        description=rec["description"],
        amount_cents=int(rec["amount_cents"]),
        category=rec.get("category"),
        note=rec.get("note"),
        recurring_id=int(recurring_id),
        recurring_due_date=due_iso,
        author=author,
    )


def month_schedule(month: str | None = None, member: int | None = None, today: date | None = None) -> dict[str, Any]:
    """Calendário de contas fixas do mês (YYYY-MM), com estado derivado: pago, pendente ou atrasado."""
    today = today or date.today()
    if month and len(month) == 7:
        year, mon = int(month[:4]), int(month[5:7])
    else:
        year, mon = today.year, today.month
        month = f"{year:04d}-{mon:02d}"
    first = date(year, mon, 1)
    last = date(year, mon, calendar.monthrange(year, mon)[1])

    match_recurring(window_start=first, window_end=last, today=today)
    recs = list_recurring(member=member, include_inactive=False)

    settled_rows = rows(
        "SELECT id, recurring_id, recurring_due_date, transaction_date, amount_cents, description "
        "FROM cash_transaction WHERE recurring_id IS NOT NULL AND deleted_at IS NULL "
        "AND recurring_due_date BETWEEN ? AND ?",
        (first.isoformat(), last.isoformat()),
    )
    settled_map = {(int(r["recurring_id"]), str(r["recurring_due_date"])): dict(r) for r in settled_rows}

    items: list[dict[str, Any]] = []
    for rec in recs:
        rid = int(rec["id"])
        for due in occurrences(rec, first, last):
            due_iso = due.isoformat()
            matched = settled_map.get((rid, due_iso))
            if matched:
                status = "pago"
                actual_cents = int(matched["amount_cents"])
            elif due < today:
                status = "atrasado"
                actual_cents = None
            else:
                status = "pendente"
                actual_cents = None
            items.append({
                "recurring_id": rid,
                "description": rec["description"],
                "account_name": rec["account_name"],
                "category": rec["category"] or "Outros",
                "frequency": rec["frequency"],
                "frequency_label": rec["frequency_label"],
                "due_date": due_iso,
                "amount_cents": int(rec["amount_cents"]),
                "actual_cents": actual_cents,
                "status": status,
                "transaction_id": int(matched["id"]) if matched else None,
                "paid_date": matched["transaction_date"] if matched else None,
            })
    items.sort(key=lambda x: (x["due_date"], x["description"]))

    expenses = [i for i in items if i["amount_cents"] < 0]
    total_planned = sum(-i["amount_cents"] for i in expenses)
    total_paid = sum(-(i["actual_cents"] if i["actual_cents"] is not None else i["amount_cents"]) for i in expenses if i["status"] == "pago")
    total_pending = sum(-i["amount_cents"] for i in expenses if i["status"] != "pago")
    return {
        "month": month,
        "items": items,
        "total_planned_cents": total_planned,
        "total_paid_cents": total_paid,
        "total_pending_cents": total_pending,
        "count_paid": sum(1 for i in items if i["status"] == "pago"),
        "count_pending": sum(1 for i in items if i["status"] == "pendente"),
        "count_overdue": sum(1 for i in items if i["status"] == "atrasado"),
    }
