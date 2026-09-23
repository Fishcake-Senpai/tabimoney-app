from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db import transaction
from app.services.formatting import money_to_cents, quantity_to_micros


TICKER_RE = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")


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
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Data inválida; use o formato AAAA-MM-DD.") from exc


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


def _instrument(connection, ticker: str, asset_class: str = "Ação", currency: str = "BRL") -> int:
    normalized = ticker.strip().upper()
    if not TICKER_RE.fullmatch(normalized):
        raise ValueError(f"Ticker B3 inválido: {ticker!r}.")
    connection.execute(
        "INSERT INTO instrument(ticker, name, asset_class, currency) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET "
        "name = CASE WHEN instrument.name = instrument.ticker THEN excluded.name ELSE instrument.name END, "
        "asset_class = CASE WHEN instrument.asset_class = 'Não classificado' THEN excluded.asset_class ELSE instrument.asset_class END, "
        "currency = excluded.currency, updated_at = CURRENT_TIMESTAMP",
        (normalized, normalized, asset_class or "Ação", currency or "BRL"),
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
                    "event_date, event_type, quantity_micros, description) "
                    "VALUES (?, ?, ?, 'manual', ?, ?, 'OPENING', ?, 'Posição inicial informada pelo usuário') "
                    "ON CONFLICT(source, external_id) DO UPDATE SET "
                    "quantity_micros = excluded.quantity_micros, sync_run_id = excluded.sync_run_id",
                    (account_id, instrument_id, run_id, opening_id, as_of_date, qty),
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
        account_alias = f"Nubank ••••{account_digits[-4:]}" if account_digits else "Nubank"
        transactions = list(getattr(statement, "transactions", []) or [])
        prepared.append((statement, account, external_key, account_type, account_alias, transactions))
        total += len(transactions)
    if not prepared:
        raise ValueError("O OFX não contém um extrato de conta reconhecível.")

    with transaction() as connection:
        run_id = _start_run(connection, "OFX Nubank")
        for statement, account, external_key, account_type, account_name, transactions in prepared:
            currency = str(getattr(statement, "currency", None) or "BRL").upper()
            connection.execute(
                "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
                "VALUES ('Nubank', ?, 'BANK', ?, 'ofx', ?) "
                "ON CONFLICT(provider, external_key) DO UPDATE SET account_name = excluded.account_name, currency = excluded.currency",
                (account_name, currency, external_key),
            )
            account_id = int(
                connection.execute(
                    "SELECT id FROM financial_account WHERE provider = 'ofx' AND external_key = ?",
                    (external_key,),
                ).fetchone()[0]
            )
            ledger = getattr(statement, "ledger_balance", None)
            ledger_date = getattr(statement, "ledger_balance_date", None)
            if ledger is not None and ledger_date is not None:
                connection.execute(
                    "INSERT INTO account_balance_snapshot(account_id, sync_run_id, source, as_of_date, balance_cents) "
                    "VALUES (?, ?, 'ofx', ?, ?) "
                    "ON CONFLICT(account_id, source, as_of_date) DO UPDATE SET "
                    "balance_cents = excluded.balance_cents, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                    (account_id, run_id, _as_date(ledger_date), money_to_cents(ledger)),
                )
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
                    "INSERT INTO cash_transaction(account_id, sync_run_id, source, external_id, transaction_date, description, amount_cents, currency) "
                    "VALUES (?, ?, 'ofx', ?, ?, ?, ?, ?) "
                    "ON CONFLICT(source, external_id) DO UPDATE SET "
                    "transaction_date = excluded.transaction_date, description = excluded.description, "
                    "amount_cents = excluded.amount_cents, sync_run_id = excluded.sync_run_id",
                    (account_id, run_id, external_id, transaction_date, description, amount, currency),
                )
        _finish_run(connection, run_id, total, f"{total} movimentação(ões) importada(s).")
    return total


def safe_ticker(value: object) -> str | None:
    ticker = str(value or "").strip().upper()
    return ticker if TICKER_RE.fullmatch(ticker) else None


def api_amount_to_cents(value: object) -> int:
    if value is None:
        return 0
    return money_to_cents(Decimal(str(value)))


def api_quantity_to_micros(value: object) -> int:
    if value is None:
        return 0
    return quantity_to_micros(Decimal(str(value)))
