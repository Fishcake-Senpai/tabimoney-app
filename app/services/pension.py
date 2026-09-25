"""Previdência privada (PGBL/VGBL) lançada a partir do extrato do banco.

PGBL e VGBL são produtos de seguradora (SUSEP): ficam no Open Insurance, não no Open Finance, então a
Pluggy não os devolve. Cada lançamento é uma fotografia do extrato (saldo e total contribuído numa data),
gravada em fixed_income_snapshot como produto 'Previdência' — e assim entra no patrimônio e na alocação
pelo mesmo caminho da renda fixa, sem tabela nova.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.db import rows, transaction
from app.services.formatting import money_to_cents
from app.services.importers import _as_date, _digest

PENSION = "Previdência"
PLAN_TYPES = ("PGBL", "VGBL")
TAX_REGIMES = ("Regressivo", "Progressivo")
THOUSANDS_ONLY = re.compile(r"^\d{1,3}(\.\d{3})+$")


def parse_amount(raw: str | None, field: str, required: bool = True) -> int | None:
    """Aceita 12345,67 · 12.345,67 · R$ 12.345 · 12345.67; '12.345' é doze mil, como se escreve no Brasil."""
    text = re.sub(r"[R$\s]", "", str(raw or ""))
    if not text:
        if required:
            raise ValueError(f"Informe {field}.")
        return None
    if THOUSANDS_ONLY.match(text):
        text = text.replace(".", "")
    try:
        cents = money_to_cents(text)
    except ValueError as exc:
        raise ValueError(f"Valor inválido para {field}: {raw}.") from exc
    if cents < 0:
        raise ValueError(f"Informe {field} sem sinal negativo.")
    return cents


def _account(connection, institution: str) -> int:
    name = f"{institution} / Previdência"
    key = _digest("pension:" + institution.casefold())
    connection.execute(
        "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
        "VALUES (?, ?, 'INVESTMENT', 'BRL', 'manual', ?) "
        "ON CONFLICT(provider, external_key) DO UPDATE SET account_name = excluded.account_name",
        (institution, name, key),
    )
    return int(connection.execute(
        "SELECT id FROM financial_account WHERE provider = 'manual' AND external_key = ?", (key,)
    ).fetchone()[0])


def plans() -> list[dict[str, Any]]:
    """Planos já lançados, com os dados do lançamento mais recente para pré-preencher o formulário."""
    return [dict(r) for r in rows(
        "SELECT f.product_key, f.name, f.issuer, f.indexer AS plan_type, f.rate AS regime, f.purchase_date, "
        "a.institution, f.as_of_date, f.invested_cents, f.gross_value_cents "
        "FROM fixed_income_snapshot f JOIN financial_account a ON a.id = f.account_id "
        "WHERE f.product_type = ? AND f.source = 'manual' AND f.id = ("
        "  SELECT g.id FROM fixed_income_snapshot g WHERE g.product_key = f.product_key AND g.source = 'manual' "
        "  ORDER BY g.as_of_date DESC, g.id DESC LIMIT 1) "
        "ORDER BY f.name", (PENSION,),
    )]


def entries() -> list[dict[str, Any]]:
    return [dict(r) for r in rows(
        "SELECT f.id, f.product_key, f.name, f.as_of_date, f.invested_cents, f.gross_value_cents, f.net_value_cents, "
        "f.source, a.institution FROM fixed_income_snapshot f JOIN financial_account a ON a.id = f.account_id "
        "WHERE f.product_type = ? ORDER BY f.as_of_date DESC, f.name", (PENSION,),
    )]


def save_entry(form: dict[str, str]) -> str:
    """Grava (ou corrige, na mesma data) o saldo de um plano. Devolve o nome do plano."""
    product_key = (form.get("product_key") or "").strip()
    existing = next((p for p in plans() if p["product_key"] == product_key), None) if product_key else None
    name = (form.get("name") or "").strip()[:120] or (existing["name"] if existing else "")
    if not name:
        raise ValueError("Informe o nome do plano (ex.: Itaú Flexprev PGBL).")
    institution = (form.get("institution") or "").strip()[:40] or (existing["institution"] if existing else "Itaú")
    plan_type = (form.get("plan_type") or "").strip().upper() or (existing["plan_type"] if existing else "")
    if plan_type and plan_type not in PLAN_TYPES:
        raise ValueError("Tipo do plano deve ser PGBL ou VGBL.")
    regime = (form.get("regime") or "").strip().capitalize() or (existing["regime"] if existing else "")
    if regime and regime not in TAX_REGIMES:
        raise ValueError("Tributação deve ser regressiva ou progressiva.")
    as_of = _as_date(form.get("as_of_date") or date.today().isoformat())
    if as_of > date.today().isoformat():
        raise ValueError("A data do saldo não pode ser futura.")
    start_raw = (form.get("start_date") or "").strip()
    start = _as_date(start_raw) if start_raw else (existing["purchase_date"] if existing else None)
    if start and start > as_of:
        raise ValueError("O início do plano não pode ser depois da data do saldo.")
    gross = parse_amount(form.get("gross"), "o saldo")
    contributed = parse_amount(form.get("contributed"), "o total contribuído", required=False)
    net = parse_amount(form.get("net"), "o saldo líquido", required=False)
    if net is not None and net > gross:
        raise ValueError("O saldo líquido de IR não pode ser maior que o saldo bruto.")
    key = existing["product_key"] if existing else "manual:prev:" + _digest(f"{institution.casefold()}:{name.casefold()}")[:24]
    with transaction() as connection:
        account_id = _account(connection, institution)
        connection.execute(
            "INSERT INTO fixed_income_snapshot(account_id, source, product_key, product_type, name, issuer, indexer, rate, "
            "as_of_date, invested_cents, gross_value_cents, net_value_cents, purchase_date) "
            "VALUES (?, 'manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(product_key, source, as_of_date) DO UPDATE SET account_id = excluded.account_id, "
            "name = excluded.name, issuer = excluded.issuer, indexer = excluded.indexer, rate = excluded.rate, "
            "invested_cents = excluded.invested_cents, gross_value_cents = excluded.gross_value_cents, "
            "net_value_cents = excluded.net_value_cents, purchase_date = excluded.purchase_date, "
            "imported_at = CURRENT_TIMESTAMP",
            (account_id, key, PENSION, name, f"{institution} Vida e Previdência", plan_type or None, regime or None,
             as_of, contributed, gross, net, start),
        )
        # nome, tipo, regime e início valem para o plano inteiro
        connection.execute(
            "UPDATE fixed_income_snapshot SET name = ?, indexer = ?, rate = ?, purchase_date = ? "
            "WHERE product_key = ? AND source = 'manual'",
            (name, plan_type or None, regime or None, start, key),
        )
    return name


def delete_entry(entry_id: int) -> None:
    with transaction() as connection:
        connection.execute(
            "DELETE FROM fixed_income_snapshot WHERE id = ? AND source = 'manual' AND product_type = ?",
            (entry_id, PENSION),
        )
