from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db import transaction
from app.services.accounts import link_accounts
from app.services.categories import categorize
from app.services.formatting import money_to_cents, quantity_to_micros


TICKER_RE = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")
BR_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        raise ValueError("Informe uma data no formato AAAA-MM-DD.")
    match = BR_DATE_RE.match(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ValueError(f"Data inválida: {text!r}.") from exc
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Data inválida; use AAAA-MM-DD ou DD/MM/AAAA.") from exc


def _csv_rows(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    if not text.strip():
        raise ValueError("O arquivo CSV está vazio.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("O CSV precisa ter uma linha de cabeçalho.")
    normalized = [str(name or "").strip().lower() for name in reader.fieldnames]
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            normalized[index]: str(value or "").strip()
            for index, value in enumerate(raw.values())
            if index < len(normalized)
        }
        if any(row.values()):
            rows.append(row)
    return rows


def _require_columns(rows: list[dict[str, str]], required: set[str]) -> None:
    if not rows:
        raise ValueError("O CSV não contém linhas de dados.")
    missing = sorted(required - rows[0].keys())
    if missing:
        raise ValueError("Colunas ausentes no CSV: " + ", ".join(missing) + ".")


def normalize_ticker(value: object) -> str | None:
    """Ticker B3 em maiúsculas; o sufixo F do mercado fracionário é removido."""
    ticker = str(value or "").strip().upper()
    if len(ticker) >= 6 and ticker.endswith("F") and TICKER_RE.fullmatch(ticker[:-1]):
        ticker = ticker[:-1]
    return ticker if TICKER_RE.fullmatch(ticker) else None


def asset_class_for(ticker: str, hint: str = "") -> str:
    """Classe provável pelo sufixo do ticker quando a origem não informa."""
    text = hint.strip()
    if text and text not in {"Ação", "Não classificado"}:
        return text
    suffix = re.sub(r"^[A-Z]{4}", "", ticker)
    if suffix in {"32", "33", "34", "35", "39"}:
        return "BDR"
    if suffix == "11":
        return "FII/ETF/Unit"
    return "Ação"


def _instrument(connection, ticker: str, asset_class: str = "Ação", currency: str = "BRL", name: str | None = None) -> int:
    normalized = normalize_ticker(ticker) or ticker.strip().upper()
    if not TICKER_RE.fullmatch(normalized):
        raise ValueError(f"Ticker B3 inválido: {ticker!r}.")
    connection.execute(
        "INSERT INTO instrument(ticker, name, asset_class, currency) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET "
        "name = CASE WHEN instrument.name = instrument.ticker THEN excluded.name ELSE instrument.name END, "
        "asset_class = CASE WHEN instrument.asset_class IN ('Não classificado', 'Ação', 'FII/ETF/Unit') "
        "AND excluded.asset_class NOT IN ('Ação', 'FII/ETF/Unit') THEN excluded.asset_class ELSE instrument.asset_class END, "
        "currency = excluded.currency, updated_at = CURRENT_TIMESTAMP",
        (normalized, name or normalized, asset_class_for(normalized, asset_class or ""), currency or "BRL"),
    )
    return int(connection.execute("SELECT id FROM instrument WHERE ticker = ?", (normalized,)).fetchone()[0])


def _manual_account(connection, account_name: str, currency: str = "BRL") -> tuple[int, str]:
    key = _digest("manual-investment:" + account_name.strip().casefold())
    connection.execute(
        "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
        "VALUES ('Importação manual', ?, 'INVESTMENT', ?, 'manual', ?) "
        "ON CONFLICT(provider, external_key) DO UPDATE SET account_name = excluded.account_name, currency = excluded.currency",
        (account_name, currency, key),
    )
    row = connection.execute(
        "SELECT id FROM financial_account WHERE provider = 'manual' AND external_key = ?", (key,)
    ).fetchone()
    return int(row[0]), key


def _start_run(connection, source: str) -> int:
    cursor = connection.execute(
        "INSERT INTO sync_run(source, status) VALUES (?, 'running')", (source,)
    )
    return int(cursor.lastrowid)


def _finish_run(connection, run_id: int, count: int, message: str = "Importação concluída.") -> None:
    connection.execute(
        "UPDATE sync_run SET finished_at = CURRENT_TIMESTAMP, status = 'success', "
        "records_read = ?, records_written = ?, message = ? WHERE id = ?",
        (count, count, message[:300], run_id),
    )


def import_positions_csv(content: bytes) -> int:
    records = _csv_rows(content)
    _require_columns(records, {"ticker", "quantity", "as_of_date"})
    with transaction() as connection:
        run_id = _start_run(connection, "CSV posições")
        for row in records:
            ticker = row["ticker"].upper()
            asset_class = row.get("asset_class", "Ação") or "Ação"
            currency = row.get("currency", "BRL").upper() or "BRL"
            account_name = row.get("account_name", "Nubank / NuInvest") or "Nubank / NuInvest"
            as_of_date = _as_date(row["as_of_date"])
            qty = quantity_to_micros(row["quantity"])
            if qty < 0:
                raise ValueError("Posições iniciais não podem ser negativas.")
            average_price = row.get("average_price", "")
            opening_cost = (
                int(round(qty * money_to_cents(average_price) / 1_000_000)) if average_price else None
            )
            account_id, account_key = _manual_account(connection, account_name, currency)
            instrument_id = _instrument(connection, ticker, asset_class, currency)
            connection.execute(
                "INSERT INTO position_snapshot(account_id, instrument_id, sync_run_id, source, as_of_date, quantity_micros) "
                "VALUES (?, ?, ?, 'manual', ?, ?) "
                "ON CONFLICT(account_id, instrument_id, source, as_of_date) DO UPDATE SET "
                "quantity_micros = excluded.quantity_micros, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (account_id, instrument_id, run_id, as_of_date, qty),
            )
            operation_events = connection.execute(
                "SELECT 1 FROM investment_event WHERE account_id = ? AND instrument_id = ? "
                "AND event_type <> 'OPENING' LIMIT 1",
                (account_id, instrument_id),
            ).fetchone()
            if not operation_events:
                opening_id = f"opening:{account_key}:{ticker}:{as_of_date}"
                connection.execute(
                    "INSERT INTO investment_event(account_id, instrument_id, sync_run_id, source, external_id, "
                    "event_date, event_type, quantity_micros, amount_cents, description) "
                    "VALUES (?, ?, ?, 'manual', ?, ?, 'OPENING', ?, ?, 'Posição inicial informada pelo usuário') "
                    "ON CONFLICT(source, external_id) DO UPDATE SET "
                    "quantity_micros = excluded.quantity_micros, amount_cents = excluded.amount_cents, "
                    "sync_run_id = excluded.sync_run_id",
                    (account_id, instrument_id, run_id, opening_id, as_of_date, qty, opening_cost),
                )
        _finish_run(connection, run_id, len(records), f"{len(records)} posição(ões) importada(s).")
    return len(records)


def import_quotes_csv(content: bytes) -> int:
    records = _csv_rows(content)
    _require_columns(records, {"ticker", "trade_date", "close"})
    with transaction() as connection:
        run_id = _start_run(connection, "CSV cotações")
        for row in records:
            ticker = row["ticker"].upper()
            trade_date = _as_date(row["trade_date"])
            close_cents = money_to_cents(row["close"])
            if close_cents < 0:
                raise ValueError("Fechamento não pode ser negativo.")
            instrument_id = _instrument(connection, ticker, row.get("asset_class", "Ação"))
            connection.execute(
                "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
                "VALUES (?, ?, ?, 'manual') "
                "ON CONFLICT(instrument_id, trade_date, provider) DO UPDATE SET "
                "close_cents = excluded.close_cents, fetched_at = CURRENT_TIMESTAMP",
                (instrument_id, trade_date, close_cents),
            )
        _finish_run(connection, run_id, len(records), f"{len(records)} fechamento(s) importado(s).")
    return len(records)


def import_ofx(content: bytes) -> int:
    try:
        from ofxparse import OfxParser

        parsed = OfxParser.parse(io.BytesIO(content))
    except Exception as exc:
        raise ValueError("Não foi possível interpretar o OFX. Confira se o arquivo é um extrato de conta válido.") from exc

    accounts = list(getattr(parsed, "accounts", []) or [])
    if not accounts:
        account = getattr(parsed, "account", None)
        if account is not None:
            accounts = [account]
    if not accounts:
        raise ValueError("O OFX não contém uma conta reconhecível.")

    prepared: list[tuple[Any, Any, str, str, str, list[Any]]] = []
    total = 0
    for account in accounts:
        statement = getattr(account, "statement", None)
        if statement is None:
            continue
        account_number = str(
            getattr(statement, "account_id", None)
            or getattr(account, "account_id", None)
            or getattr(account, "number", None)
            or "conta-sem-numero"
        )
        bank_id = str(getattr(statement, "routing_number", None) or getattr(account, "bank_id", None) or "")
        account_type = str(getattr(statement, "account_type", None) or getattr(account, "account_type", None) or "CONTA")
        external_key = _digest("ofx:" + bank_id + ":" + account_type + ":" + account_number)
        account_digits = re.sub(r"\D", "", account_number)
        kind = "CREDIT" if _is_credit_ofx(account) else "BANK"
        base_alias = "Nubank Cartão" if kind == "CREDIT" else "Nubank"
        account_alias = f"{base_alias} ••••{account_digits[-4:]}" if account_digits else base_alias
        transactions = list(getattr(statement, "transactions", []) or [])
        prepared.append((statement, kind, external_key, account_type, account_alias, transactions))
        total += len(transactions)
    if not prepared:
        raise ValueError("O OFX não contém um extrato de conta reconhecível.")

    with transaction() as connection:
        run_id = _start_run(connection, "OFX Nubank")
        for statement, kind, external_key, account_type, account_name, transactions in prepared:
            currency = str(getattr(statement, "currency", None) or "BRL").upper()
            connection.execute(
                "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
                "VALUES ('Nubank', ?, ?, ?, 'ofx', ?) "
                "ON CONFLICT(provider, external_key) DO UPDATE SET account_name = excluded.account_name, "
                "account_type = excluded.account_type, currency = excluded.currency",
                (account_name, kind, currency, external_key),
            )
            account_id = int(
                connection.execute(
                    "SELECT id FROM financial_account WHERE provider = 'ofx' AND external_key = ?",
                    (external_key,),
                ).fetchone()[0]
            )
            # ofxparse expõe o LEDGERBAL como balance/balance_date.
            ledger = getattr(statement, "balance", None)
            ledger_date = getattr(statement, "balance_date", None) or getattr(statement, "end_date", None)
            if ledger is not None and ledger_date is not None:
                connection.execute(
                    "INSERT INTO account_balance_snapshot(account_id, sync_run_id, source, as_of_date, balance_cents) "
                    "VALUES (?, ?, 'ofx', ?, ?) "
                    "ON CONFLICT(account_id, source, as_of_date) DO UPDATE SET "
                    "balance_cents = excluded.balance_cents, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                    (account_id, run_id, _as_date(ledger_date), _ofx_balance(ledger, kind)),
                )
            statement_end = getattr(statement, "end_date", None) or ledger_date
            statement_ref = _as_date(statement_end) if kind == "CREDIT" and statement_end else None
            for item in transactions:
                transaction_date = _as_date(getattr(item, "date", None))
                payee = str(getattr(item, "payee", None) or "").strip()
                memo = str(getattr(item, "memo", None) or "").strip()
                description = " — ".join(part for part in (payee, memo) if part) or "Movimentação OFX"
                amount = money_to_cents(getattr(item, "amount", 0))
                fitid = str(getattr(item, "fitid", None) or "").strip()
                external_id = f"{external_key}:{fitid}" if fitid else _digest(
                    f"{external_key}|{transaction_date}|{description}|{amount}"
                )
                connection.execute(
                    "INSERT INTO cash_transaction(account_id, sync_run_id, source, external_id, transaction_date, "
                    "description, amount_cents, currency, category, statement_ref) "
                    "VALUES (?, ?, 'ofx', ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(source, external_id) DO UPDATE SET "
                    "transaction_date = excluded.transaction_date, description = excluded.description, "
                    "amount_cents = excluded.amount_cents, sync_run_id = excluded.sync_run_id, "
                    "category = COALESCE(cash_transaction.category, excluded.category), "
                    "statement_ref = COALESCE(excluded.statement_ref, cash_transaction.statement_ref)",
                    (account_id, run_id, external_id, transaction_date, description, amount, currency,
                     categorize(description), statement_ref),
                )
        link_accounts(connection)
        _finish_run(connection, run_id, total, f"{total} movimentação(ões) importada(s).")
    return total


def _is_credit_ofx(account: Any) -> bool:
    from ofxparse.ofxparse import AccountType

    account_type = str(getattr(account, "account_type", "") or "").lower()
    return getattr(account, "type", None) == AccountType.CreditCard or "credit" in account_type


def _ofx_balance(ledger: object, kind: str) -> int:
    """Cartão é gravado sempre como saldo negativo (dívida); conta mantém o sinal do OFX."""
    cents = money_to_cents(ledger)
    return -abs(cents) if kind == "CREDIT" else cents


def safe_ticker(value: object) -> str | None:
    return normalize_ticker(value)


def api_amount_to_cents(value: object) -> int:
    if value is None:
        return 0
    return money_to_cents(Decimal(str(value)))


def api_quantity_to_micros(value: object) -> int:
    if value is None:
        return 0
    return quantity_to_micros(Decimal(str(value)))
