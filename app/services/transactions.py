"""Lançamentos manuais, edição, flags (ignorar / fora do resultado), CSV, comprovantes,
desfazer importação e pendências dispensadas."""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from app import db
from app.db import rows, transaction
from app.services import spending
from app.services.categories import categorize

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
CASH_ACCOUNT_KEY = "manual:carteira"
CASH_ACCOUNT_NAME = "Carteira (dinheiro)"
PENDING_KINDS = ("transfer_orphan", "position", "bank")
PENDING_EXPIRY_DAYS = 60  # sugestões paradas expiram em 2 meses


def _clean_date(value: str) -> str:
    text = (value or "").strip()
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        d, m, y = text.split("/")
        text = f"{y}-{m}-{d}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError("Data inválida. Use AAAA-MM-DD ou DD/MM/AAAA.") from exc


def _clean_description(value: str) -> str:
    text = " ".join((value or "").split())[:200]
    if not text:
        raise ValueError("Informe a descrição do lançamento.")
    return text


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()[:500]
    return text or None


# ---------------------------------------------------------------- contas para lançamento manual

def cash_accounts(member: int | None = None) -> list[dict[str, Any]]:
    """Contas bancárias e cartões disponíveis para lançar à mão."""
    if member is None:
        data = rows(
            "SELECT id, account_name, account_type, institution, provider, COALESCE(member_id, 1) AS member_id "
            "FROM financial_account WHERE account_type IN ('BANK', 'CREDIT') ORDER BY account_type, account_name"
        )
    else:
        data = rows(
            "SELECT id, account_name, account_type, institution, provider, COALESCE(member_id, 1) AS member_id "
            "FROM financial_account WHERE account_type IN ('BANK', 'CREDIT') AND COALESCE(member_id, 1) = ? "
            "ORDER BY account_type, account_name",
            (member,),
        )
    return [dict(r) for r in data]


def ensure_cash_account(member: int | None = None) -> int:
    """Garante uma conta 'Carteira (dinheiro)' para registrar gastos em espécie ou ajustes."""
    found = rows(
        "SELECT id FROM financial_account WHERE provider = 'manual' AND external_key = ?",
        (CASH_ACCOUNT_KEY,),
    )
    if found:
        return int(found[0]["id"])
    with transaction() as conn:
        conn.execute(
            "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key, member_id) "
            "VALUES ('Manual', ?, 'BANK', 'BRL', 'manual', ?, ?) "
            "ON CONFLICT(provider, external_key) DO NOTHING",
            (CASH_ACCOUNT_NAME, CASH_ACCOUNT_KEY, member or 1),
        )
        row = conn.execute(
            "SELECT id FROM financial_account WHERE provider = 'manual' AND external_key = ?",
            (CASH_ACCOUNT_KEY,),
        ).fetchone()
        return int(row["id"])


def resolve_account_id(account: int | str | None, member: int | None = None) -> int:
    """Aceita id numérico, nome da conta, ou 'dinheiro'/vazio (usa/cria Carteira)."""
    if account is None or (isinstance(account, str) and account.strip().lower() in {"", "dinheiro", "carteira"}):
        return ensure_cash_account(member)
    if isinstance(account, int) or (isinstance(account, str) and account.strip().isdigit()):
        aid = int(account)
        found = rows("SELECT id FROM financial_account WHERE id = ? AND account_type IN ('BANK', 'CREDIT')", (aid,))
        if not found:
            raise ValueError("Conta não encontrada.")
        return aid
    name = spending.normalize(str(account))
    for acc in cash_accounts(member):
        if spending.normalize(acc["account_name"]) == name:
            return int(acc["id"])
    raise ValueError(f"Conta '{account}' não encontrada.")


# ---------------------------------------------------------------- criar / editar / excluir

def create_transaction(
    *,
    account_id: int | str | None,
    transaction_date: str,
    description: str,
    amount_cents: int,
    category: str | None = None,
    note: str | None = None,
    is_ignored: bool = False,
    exclude_from_pnl: bool = False,
    recurring_id: int | None = None,
    recurring_due_date: str | None = None,
    member: int | None = None,
    author: str = "usuario",
) -> dict[str, Any]:
    """Cria um lançamento manual. amount_cents negativo = saída, positivo = entrada."""
    if int(amount_cents) == 0:
        raise ValueError("O valor do lançamento não pode ser zero.")
    aid = resolve_account_id(account_id, member=member)
    iso_date = _clean_date(transaction_date)
    desc = _clean_description(description)
    clean_note = _clean_note(note)
    acc = rows("SELECT account_name, account_type FROM financial_account WHERE id = ?", (aid,))[0]
    auto_cat = categorize(desc)
    user_cat = spending.clean_category(category) if category and category.strip() else None
    ext_id = f"manual:{uuid.uuid4().hex}"
    with transaction() as conn:
        if user_cat:
            spending._register(conn, user_cat, author)
        cursor = conn.execute(
            "INSERT INTO cash_transaction("
            "account_id, source, external_id, transaction_date, description, amount_cents, status, currency, "
            "category, user_category, note, is_ignored, exclude_from_pnl, recurring_id, recurring_due_date"
            ") VALUES (?, 'manual', ?, ?, ?, ?, 'POSTED', 'BRL', ?, ?, ?, ?, ?, ?, ?)",
            (
                aid, ext_id, iso_date, desc, int(amount_cents), auto_cat, user_cat, clean_note,
                1 if is_ignored else 0, 1 if exclude_from_pnl else 0,
                recurring_id, recurring_due_date,
            ),
        )
        tx_id = int(cursor.lastrowid)
    return {
        "id": tx_id,
        "account_id": aid,
        "account_name": acc["account_name"],
        "transaction_date": iso_date,
        "description": desc,
        "amount_cents": int(amount_cents),
        "category": user_cat or auto_cat,
        "note": clean_note,
        "is_ignored": bool(is_ignored),
        "exclude_from_pnl": bool(exclude_from_pnl),
        "source": "manual",
    }


def update_transaction(
    transaction_id: int,
    *,
    transaction_date: str | None = None,
    description: str | None = None,
    amount_cents: int | None = None,
    category: str | None = ...,  # type: ignore[assignment]
    note: str | None = ...,  # type: ignore[assignment]
    is_ignored: bool | None = None,
    exclude_from_pnl: bool | None = None,
    account_id: int | str | None = None,
    author: str = "usuario",
) -> dict[str, Any]:
    """Edita um lançamento existente (manual ou importado). Mantém external_id para evitar duplicação."""
    found = rows(
        "SELECT id, account_id, transaction_date, description, amount_cents, category, user_category, "
        "note, is_ignored, exclude_from_pnl, source FROM cash_transaction WHERE id = ? AND deleted_at IS NULL",
        (int(transaction_id),),
    )
    if not found:
        raise ValueError("Lançamento não encontrado.")
    current = dict(found[0])

    updates: dict[str, Any] = {}
    if account_id is not None:
        updates["account_id"] = resolve_account_id(account_id)
    if transaction_date is not None:
        updates["transaction_date"] = _clean_date(transaction_date)
    if description is not None:
        updates["description"] = _clean_description(description)
    if amount_cents is not None:
        if int(amount_cents) == 0:
            raise ValueError("O valor do lançamento não pode ser zero.")
        updates["amount_cents"] = int(amount_cents)
    if category is not ...:
        updates["user_category"] = spending.clean_category(category) if category and category.strip() else None
    if note is not ...:
        updates["note"] = _clean_note(note)
    if is_ignored is not None:
        updates["is_ignored"] = 1 if is_ignored else 0
    if exclude_from_pnl is not None:
        updates["exclude_from_pnl"] = 1 if exclude_from_pnl else 0

    if updates:
        with transaction() as conn:
            if updates.get("user_category"):
                spending._register(conn, updates["user_category"], author)
            cols = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE cash_transaction SET {cols} WHERE id = ?", (*updates.values(), int(transaction_id)))

    updated = dict(rows(
        "SELECT t.id, t.account_id, a.account_name, t.transaction_date, t.description, t.amount_cents, "
        "COALESCE(t.user_category, t.category) AS category, t.note, t.is_ignored, t.exclude_from_pnl, t.source "
        "FROM cash_transaction t JOIN financial_account a ON a.id = t.account_id WHERE t.id = ?",
        (int(transaction_id),),
    )[0])
    updated["is_ignored"] = bool(updated["is_ignored"])
    updated["exclude_from_pnl"] = bool(updated["exclude_from_pnl"])
    return updated


def delete_transaction(transaction_id: int) -> dict[str, Any]:
    """Exclusão reversível (marca deleted_at) de um lançamento manual."""
    found = rows(
        "SELECT id, source, description, deleted_at FROM cash_transaction WHERE id = ?",
        (int(transaction_id),),
    )
    if not found:
        raise ValueError("Lançamento não encontrado.")
    row = found[0]
    if row["deleted_at"]:
        return {"id": int(transaction_id), "excluido": False, "motivo": "já estava excluído"}
    if row["source"] != "manual":
        raise ValueError("Só lançamentos criados à mão podem ser excluídos. Para lançamentos importados, use 'Ignorar'.")
    with transaction() as conn:
        conn.execute("UPDATE cash_transaction SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (int(transaction_id),))
    return {"id": int(transaction_id), "excluido": True, "descricao": row["description"]}


def description_suggestions(query: str = "", limit: int = 20) -> list[str]:
    """Sugestões de descrição a partir do histórico recente de lançamentos."""
    q = spending.normalize(query)
    data = rows(
        "SELECT description, COUNT(*) AS freq, MAX(transaction_date) AS last_date "
        "FROM cash_transaction WHERE deleted_at IS NULL AND description <> '' "
        "GROUP BY description ORDER BY freq DESC, last_date DESC LIMIT 200"
    )
    seen: set[str] = set()
    output: list[str] = []
    for r in data:
        desc = str(r["description"]).strip()
        norm = spending.normalize(desc)
        if norm in seen:
            continue
        if q and q not in norm:
            continue
        seen.add(norm)
        output.append(desc)
        if len(output) >= limit:
            break
    return output


# ---------------------------------------------------------------- ignorar / fora do resultado

def set_flags(
    transaction_ids: list[int],
    *,
    is_ignored: bool | None = None,
    exclude_from_pnl: bool | None = None,
) -> int:
    """Marca ou desmarca ignorado / fora do resultado em um ou vários lançamentos."""
    ids = [int(i) for i in transaction_ids]
    if not ids:
        return 0
    parts: list[str] = []
    params: list[Any] = []
    if is_ignored is not None:
        parts.append("is_ignored = ?")
        params.append(1 if is_ignored else 0)
    if exclude_from_pnl is not None:
        parts.append("exclude_from_pnl = ?")
        params.append(1 if exclude_from_pnl else 0)
    if not parts:
        return 0
    marks = ",".join("?" * len(ids))
    with transaction() as conn:
        cursor = conn.execute(
            f"UPDATE cash_transaction SET {', '.join(parts)} WHERE id IN ({marks}) AND deleted_at IS NULL",
            (*params, *ids),
        )
        return cursor.rowcount


def set_category_exclude_from_pnl(name: str, exclude: bool, author: str = "usuario") -> dict[str, Any]:
    """Marca/desmarca uma categoria inteira como fora do resultado (continua contando no saldo)."""
    cat = spending.clean_category(name)
    key = spending.normalize(cat)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO category(name, name_key, author, exclude_from_pnl) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name_key) DO UPDATE SET exclude_from_pnl = excluded.exclude_from_pnl",
            (cat, key, author, 1 if exclude else 0),
        )
    return {"categoria": cat, "fora_do_resultado": bool(exclude)}


def excluded_pnl_categories() -> set[str]:
    """Nomes normalizados das categorias marcadas como fora do resultado."""
    return {
        str(r["name_key"])
        for r in rows("SELECT name_key FROM category WHERE exclude_from_pnl = 1 AND deleted_at IS NULL")
    }


# ---------------------------------------------------------------- exportar CSV

def export_csv(transactions: list[dict[str, Any]]) -> bytes:
    """Exporta lançamentos em CSV (UTF-8 com BOM, separador ';', compatível com Excel em português)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([
        "ID", "Data", "Descrição", "Categoria", "Conta", "Valor", "Status",
        "Ignorado", "Fora do resultado", "Conta fixa", "Nota", "Comprovantes",
    ])
    for t in transactions:
        amount = f"{int(t['amount_cents']) / 100:.2f}".replace(".", ",")
        writer.writerow([
            t["id"],
            t["transaction_date"],
            t["description"],
            t.get("category") or "",
            t.get("account_name") or "",
            amount,
            t.get("status") or "POSTED",
            "Sim" if t.get("is_ignored") else "Não",
            "Sim" if t.get("exclude_from_pnl") or t.get("effective_exclude_from_pnl") else "Não",
            "Sim" if t.get("recurring_id") else "Não",
            t.get("note") or "",
            int(t.get("attachment_count") or 0),
        ])
    return buf.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------- comprovantes (anexos)

def attachments_dir() -> Path:
    path = db.data_dir() / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(filename: str) -> tuple[str, str]:
    base = Path(filename or "comprovante").name
    base = re.sub(r"[^\w.\- ()]", "_", base).strip() or "comprovante"
    ext = Path(base).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"Tipo de arquivo não aceito. Envie: {allowed}.")
    return base[:120], ext


def add_attachment(transaction_id: int, filename: str, content: bytes, mime_type: str | None = None) -> dict[str, Any]:
    """Salva um comprovante no disco local (data_dir/attachments) e vincula ao lançamento."""
    found = rows("SELECT id FROM cash_transaction WHERE id = ? AND deleted_at IS NULL", (int(transaction_id),))
    if not found:
        raise ValueError("Lançamento não encontrado.")
    if not content:
        raise ValueError("O arquivo está vazio.")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError("O comprovante passa do limite de 10 MB.")
    clean_name, ext = _safe_filename(filename)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    resolved_mime = ALLOWED_EXTENSIONS[ext]
    if mime_type and mime_type.split(";")[0].strip().lower() in set(ALLOWED_EXTENSIONS.values()):
        resolved_mime = mime_type.split(";")[0].strip().lower()
    target = attachments_dir() / stored_name
    target.write_bytes(content)
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO transaction_attachment(transaction_id, filename, stored_name, mime_type, size_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(transaction_id), clean_name, stored_name, resolved_mime, len(content)),
        )
        att_id = int(cursor.lastrowid)
    return {
        "id": att_id,
        "transaction_id": int(transaction_id),
        "filename": clean_name,
        "mime_type": resolved_mime,
        "size_bytes": len(content),
    }


def list_attachments(transaction_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in rows(
            "SELECT id, transaction_id, filename, mime_type, size_bytes, uploaded_at "
            "FROM transaction_attachment WHERE transaction_id = ? AND deleted_at IS NULL ORDER BY id DESC",
            (int(transaction_id),),
        )
    ]


def attachment_counts() -> dict[int, int]:
    return {
        int(r["transaction_id"]): int(r["n"])
        for r in rows(
            "SELECT transaction_id, COUNT(*) AS n FROM transaction_attachment "
            "WHERE deleted_at IS NULL GROUP BY transaction_id"
        )
    }


def get_attachment(attachment_id: int) -> tuple[dict[str, Any], Path]:
    found = rows(
        "SELECT id, transaction_id, filename, stored_name, mime_type, size_bytes "
        "FROM transaction_attachment WHERE id = ? AND deleted_at IS NULL",
        (int(attachment_id),),
    )
    if not found:
        raise ValueError("Comprovante não encontrado.")
    row = dict(found[0])
    path = (attachments_dir() / Path(row["stored_name"]).name).resolve()
    if path.parent != attachments_dir().resolve() or not path.exists():
        raise ValueError("Arquivo do comprovante não encontrado no disco.")
    return row, path


def delete_attachment(attachment_id: int) -> dict[str, Any]:
    found = rows(
        "SELECT id, transaction_id, filename, stored_name FROM transaction_attachment WHERE id = ? AND deleted_at IS NULL",
        (int(attachment_id),),
    )
    if not found:
        raise ValueError("Comprovante não encontrado.")
    row = dict(found[0])
    with transaction() as conn:
        conn.execute("UPDATE transaction_attachment SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (int(attachment_id),))
    return {"id": int(attachment_id), "transaction_id": int(row["transaction_id"]), "filename": row["filename"]}


# ---------------------------------------------------------------- desfazer importação

def undo_import(run_id: int) -> dict[str, Any]:
    """Desfaz uma importação: remove o lote gravado por aquele sync_run_id.
    Lançamentos de caixa são marcados com deleted_at; eventos/posições/saldos são removidos para recalcular a carteira."""
    found = rows("SELECT id, source, status, records_written, undone_at FROM sync_run WHERE id = ?", (int(run_id),))
    if not found:
        raise ValueError("Importação não encontrada.")
    run = dict(found[0])
    if run["undone_at"]:
        raise ValueError("Esta importação já foi desfeita.")
    with transaction() as conn:
        tx_count = conn.execute(
            "UPDATE cash_transaction SET deleted_at = CURRENT_TIMESTAMP WHERE sync_run_id = ? AND deleted_at IS NULL",
            (int(run_id),),
        ).rowcount
        ev_count = conn.execute("DELETE FROM investment_event WHERE sync_run_id = ?", (int(run_id),)).rowcount
        pos_count = conn.execute("DELETE FROM position_snapshot WHERE sync_run_id = ?", (int(run_id),)).rowcount
        bal_count = conn.execute("DELETE FROM account_balance_snapshot WHERE sync_run_id = ?", (int(run_id),)).rowcount
        fi_count = conn.execute("DELETE FROM fixed_income_snapshot WHERE sync_run_id = ?", (int(run_id),)).rowcount
        conn.execute("UPDATE sync_run SET undone_at = CURRENT_TIMESTAMP WHERE id = ?", (int(run_id),))
    return {
        "run_id": int(run_id),
        "source": run["source"],
        "lancamentos": tx_count,
        "eventos_investimento": ev_count,
        "posicoes": pos_count,
        "saldos": bal_count,
        "renda_fixa": fi_count,
        "total_desfeito": tx_count + ev_count + pos_count + bal_count + fi_count,
    }


# ---------------------------------------------------------------- pendências que não voltam

def dismiss_pending(kind: str, entity_key: str) -> dict[str, Any]:
    """Dispensa uma pendência (transferência sem par, posição ou saldo) para que nunca volte a aparecer."""
    if kind not in PENDING_KINDS:
        raise ValueError(f"Tipo de pendência inválido: {kind!r}.")
    key = (entity_key or "").strip()
    if not key:
        raise ValueError("Informe a chave da pendência.")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO dismissed_pending(kind, entity_key, dismissed_at, expires_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP, NULL) "
            "ON CONFLICT(kind, entity_key) DO UPDATE SET dismissed_at = CURRENT_TIMESTAMP, expires_at = NULL",
            (kind, key),
        )
    return {"kind": kind, "entity_key": key, "dispensada": True}


def dismissed_keys(kind: str) -> set[str]:
    """Chaves dispensadas (ou dentro do prazo de expiração) para um tipo de pendência."""
    return {
        str(r["entity_key"])
        for r in rows(
            "SELECT entity_key FROM dismissed_pending "
            "WHERE kind = ? AND (expires_at IS NULL OR expires_at > date('now', 'localtime'))",
            (kind,),
        )
    }


def restore_dismissed(kind: str | None = None) -> int:
    """Limpa pendências dispensadas, se o usuário quiser vê-las novamente."""
    with transaction() as conn:
        if kind:
            return conn.execute("DELETE FROM dismissed_pending WHERE kind = ?", (kind,)).rowcount
        return conn.execute("DELETE FROM dismissed_pending").rowcount
