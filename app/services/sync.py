from __future__ import annotations

import hashlib
import re
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.db import get_setting, rows, set_setting, transaction
from app.providers.brapi import BrapiError, latest_daily_close
from app.providers.pluggy import PluggyClient, PluggyData, PluggyError
from app.security import get_secret
from app.services.importers import api_amount_to_cents, api_quantity_to_micros, safe_ticker


class SyncError(RuntimeError):
    pass


def _day(value: object, fallback: date | None = None) -> str:
    default = fallback or date.today()
    if not value:
        return default.isoformat()
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else default.isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_start(source: str) -> int:
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO sync_run(source, status) VALUES (?, 'running')", (source,)
        )
        return int(cursor.lastrowid)


def _run_finish(
    run_id: int,
    status: str,
    records_read: int,
    records_written: int,
    message: str,
    external_updated_at: str | None = None,
) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE sync_run SET finished_at = CURRENT_TIMESTAMP, external_updated_at = ?, status = ?, "
            "records_read = ?, records_written = ?, message = ? WHERE id = ?",
            (external_updated_at, status, records_read, records_written, message[:500], run_id),
        )


def _instrument(connection, ticker: str, name: str, asset_class: str, currency: str = "BRL") -> int:
    connection.execute(
        "INSERT INTO instrument(ticker, name, asset_class, currency) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET "
        "name = CASE WHEN instrument.name = instrument.ticker THEN excluded.name ELSE instrument.name END, "
        "asset_class = CASE WHEN instrument.asset_class = 'Não classificado' THEN excluded.asset_class ELSE instrument.asset_class END, "
        "currency = excluded.currency, updated_at = CURRENT_TIMESTAMP",
        (ticker, name or ticker, asset_class, currency or "BRL"),
    )
    return int(connection.execute("SELECT id FROM instrument WHERE ticker = ?", (ticker,)).fetchone()[0])


def _asset_class(investment: dict[str, Any]) -> str:
    subtype = str(investment.get("subtype") or "").upper()
    kind = str(investment.get("type") or "").upper()
    if "BDR" in subtype:
        return "BDR"
    if "FII" in subtype or "REAL_ESTATE" in subtype:
        return "FII"
    if kind == "ETF":
        return "ETF"
    if kind == "EQUITY":
        return "Ação"
    return "Ação"


def _is_supported_candidate(investment: dict[str, Any]) -> bool:
    kind = str(investment.get("type") or "").upper()
    subtype = str(investment.get("subtype") or "").upper()
    return kind in {"EQUITY", "ETF"} or any(
        label in subtype for label in ("BDR", "FII", "STOCK", "EQUITY", "ETF")
    )


def _investment_ticker(investment: dict[str, Any]) -> str | None:
    for field in ("ticker", "symbol", "code"):
        ticker = safe_ticker(investment.get(field))
        if ticker:
            return ticker
    return None


def _signed_event_quantity(event_type: str, raw_quantity: object) -> int:
    quantity = api_quantity_to_micros(raw_quantity)
    normalized = event_type.upper()
    if normalized in {"SELL", "TRANSFER_OUT"}:
        return -abs(quantity)
    if normalized in {"BUY", "TRANSFER_IN", "OPENING", "SPLIT"}:
        return abs(quantity)
    return 0


def _write_pluggy_data(connection, item_id: str, payload: PluggyData, run_id: int) -> tuple[int, int]:
    written = 0
    records_read = len(payload.accounts) + len(payload.investments)
    connector = payload.item.get("connector")
    if isinstance(connector, dict):
        institution = str(connector.get("name") or "Open Finance")
    else:
        institution = str(connector or "Open Finance")
    snapshot_day = _day(
        payload.item.get("lastUpdatedAt") or payload.item.get("updatedAt") or payload.item.get("dataUpdatedAt")
    )

    account_ids: dict[str, int] = {}
    for account in payload.accounts:
        external_id = str(account.get("id") or "")
        if not external_id:
            continue
        external_key = f"item:{item_id}:account:{external_id}"
        currency = str(account.get("currencyCode") or "BRL").upper()
        account_type = str(account.get("type") or "BANK").upper()
        account_digits = re.sub(r"\D", "", str(account.get("number") or ""))
        account_suffix = account_digits[-4:]
        account_name = f"Nubank ••••{account_suffix}" if account_type == "BANK" and account_suffix else (
            "Nubank" if account_type == "BANK" else f"Nubank / {account.get('subtype') or account_type}"
        )
        connection.execute(
            "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
            "VALUES (?, ?, ?, ?, 'pluggy', ?) "
            "ON CONFLICT(provider, external_key) DO UPDATE SET institution = excluded.institution, "
            "account_name = excluded.account_name, account_type = excluded.account_type, currency = excluded.currency",
            (institution, account_name, account_type, currency, external_key),
        )
        account_id = int(
            connection.execute(
                "SELECT id FROM financial_account WHERE provider = 'pluggy' AND external_key = ?",
                (external_key,),
            ).fetchone()[0]
        )
        account_ids[external_id] = account_id
        if account.get("balance") is not None:
            as_of = _day(account.get("updatedAt"), date.fromisoformat(snapshot_day))
            connection.execute(
                "INSERT INTO account_balance_snapshot(account_id, sync_run_id, source, as_of_date, balance_cents) "
                "VALUES (?, ?, 'pluggy', ?, ?) "
                "ON CONFLICT(account_id, source, as_of_date) DO UPDATE SET "
                "balance_cents = excluded.balance_cents, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (account_id, run_id, as_of, api_amount_to_cents(account.get("balance"))),
            )
            written += 1
        transactions = payload.transactions_by_account.get(external_id, [])
        records_read += len(transactions)
        for item in transactions:
            source_id = str(item.get("id") or "").strip()
            transaction_day = _day(item.get("date"), date.fromisoformat(snapshot_day))
            description = str(item.get("description") or item.get("descriptionRaw") or "Movimentação Open Finance")[:250]
            raw_amount = api_amount_to_cents(item.get("amount"))
            direction = str(item.get("type") or "").upper()
            signed_amount = -abs(raw_amount) if direction == "DEBIT" or raw_amount < 0 else abs(raw_amount)
            raw_status = str(item.get("status") or "UNKNOWN").upper()
            transaction_status = raw_status if raw_status in {"POSTED", "PENDING"} else "UNKNOWN"
            if not source_id:
                source_id = _sha(f"{external_id}|{transaction_day}|{description}|{signed_amount}")
            transaction_key = f"{external_id}:{source_id}"
            connection.execute(
                "INSERT INTO cash_transaction(account_id, sync_run_id, source, external_id, transaction_date, description, amount_cents, status, currency) "
                "VALUES (?, ?, 'pluggy', ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, external_id) DO UPDATE SET transaction_date = excluded.transaction_date, "
                "description = excluded.description, amount_cents = excluded.amount_cents, status = excluded.status, "
                "currency = excluded.currency, sync_run_id = excluded.sync_run_id",
                (account_id, run_id, transaction_key, transaction_day, description, signed_amount, transaction_status, currency),
            )
            written += 1

    investment_account_key = f"item:{item_id}:investments"
    connection.execute(
        "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
        "VALUES (?, 'Nubank / NuInvest', 'INVESTMENT', 'BRL', 'pluggy', ?) "
        "ON CONFLICT(provider, external_key) DO UPDATE SET institution = excluded.institution, account_name = excluded.account_name",
        (institution, investment_account_key),
    )
    investment_account_id = int(
        connection.execute(
            "SELECT id FROM financial_account WHERE provider = 'pluggy' AND external_key = ?",
            (investment_account_key,),
        ).fetchone()[0]
    )
    records_read += sum(len(entries) for entries in payload.investment_transactions.values())
    current_instrument_ids: set[int] = set()
    manual_account = connection.execute(
        "SELECT id FROM financial_account WHERE provider = 'manual' AND account_name = 'Nubank / NuInvest' LIMIT 1"
    ).fetchone()
    if payload.positions_complete:
        for investment in payload.investments:
            ticker = _investment_ticker(investment)
            quantity = investment.get("quantity")
            inactive = str(investment.get("status") or "").upper() in {"INACTIVE", "CLOSED", "REDEEMED"}
            if ticker is None or (quantity is None and not inactive):
                continue
            quantity_micros = 0 if inactive else api_quantity_to_micros(quantity)
            instrument_id = _instrument(
                connection,
                ticker,
                str(investment.get("name") or ticker),
                _asset_class(investment),
                str(investment.get("currencyCode") or "BRL").upper(),
            )
            if manual_account:
                opening = connection.execute(
                    "SELECT event_date, quantity_micros FROM investment_event "
                    "WHERE account_id = ? AND instrument_id = ? AND event_type = 'OPENING' "
                    "ORDER BY event_date DESC, id DESC LIMIT 1",
                    (int(manual_account[0]), instrument_id),
                ).fetchone()
                if opening:
                    seed_id = f"manual-opening-seed:{int(manual_account[0])}:{instrument_id}"
                    connection.execute(
                        "INSERT INTO investment_event(account_id, instrument_id, sync_run_id, source, external_id, "
                        "event_date, event_type, quantity_micros, description) "
                        "VALUES (?, ?, ?, 'pluggy', ?, ?, 'OPENING', ?, 'Abertura conciliada com posição manual') "
                        "ON CONFLICT(source, external_id) DO UPDATE SET event_date = excluded.event_date, "
                        "quantity_micros = excluded.quantity_micros, sync_run_id = excluded.sync_run_id",
                        (investment_account_id, instrument_id, run_id, seed_id, opening["event_date"], opening["quantity_micros"]),
                    )
            current_instrument_ids.add(instrument_id)
            invest_date = snapshot_day
            connection.execute(
                "INSERT INTO position_snapshot(account_id, instrument_id, sync_run_id, source, as_of_date, quantity_micros) "
                "VALUES (?, ?, ?, 'pluggy', ?, ?) "
                "ON CONFLICT(account_id, instrument_id, source, as_of_date) DO UPDATE SET "
                "quantity_micros = excluded.quantity_micros, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (investment_account_id, instrument_id, run_id, invest_date, quantity_micros),
            )
            written += 1

    for investment in payload.investments:
        ticker = _investment_ticker(investment)
        if ticker is None:
            continue
        investment_id = str(investment.get("id") or "")
        if not investment_id:
            continue
        instrument_row = connection.execute(
            "SELECT id FROM instrument WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not instrument_row:
            continue
        instrument_id = int(instrument_row[0])
        for event in payload.investment_transactions.get(investment_id, []):
            event_type = str(event.get("type") or "OTHER").upper()
            event_day = _day(event.get("tradeDate") or event.get("date"), date.fromisoformat(snapshot_day))
            raw_event_id = str(event.get("id") or "").strip()
            description = str(event.get("description") or "")[:250] or None
            raw_quantity = event.get("quantity")
            signed_quantity = _signed_event_quantity(event_type, raw_quantity)
            amount_cents = api_amount_to_cents(event.get("netAmount", event.get("amount")))
            raw_unit_price = event.get("value")
            unit_price = api_amount_to_cents(raw_unit_price) if raw_unit_price is not None else None
            event_id = raw_event_id or _sha(
                f"{investment_id}|{event_day}|{event_type}|{signed_quantity}|{amount_cents}|{description or ''}"
            )
            external_id = f"{investment_id}:{event_id}"
            connection.execute(
                "INSERT INTO investment_event(account_id, instrument_id, sync_run_id, source, external_id, event_date, "
                "event_type, quantity_micros, amount_cents, unit_price_cents, description) "
                "VALUES (?, ?, ?, 'pluggy', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, external_id) DO UPDATE SET event_date = excluded.event_date, event_type = excluded.event_type, "
                "quantity_micros = excluded.quantity_micros, amount_cents = excluded.amount_cents, "
                "unit_price_cents = excluded.unit_price_cents, description = excluded.description, sync_run_id = excluded.sync_run_id",
                (investment_account_id, instrument_id, run_id, external_id, event_day, event_type, signed_quantity, amount_cents, unit_price, description),
            )
            written += 1

    if payload.positions_complete:
        known_rows = connection.execute(
            "SELECT DISTINCT instrument_id FROM position_snapshot WHERE account_id = ? AND source = 'pluggy'",
            (investment_account_id,),
        ).fetchall()
        for known in known_rows:
            instrument_id = int(known[0])
            if instrument_id in current_instrument_ids:
                continue
            connection.execute(
                "INSERT INTO position_snapshot(account_id, instrument_id, sync_run_id, source, as_of_date, quantity_micros) "
                "VALUES (?, ?, ?, 'pluggy', ?, 0) "
                "ON CONFLICT(account_id, instrument_id, source, as_of_date) DO UPDATE SET "
                "quantity_micros = 0, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (investment_account_id, instrument_id, run_id, snapshot_day),
            )
            written += 1
    return records_read, written


def sync_pluggy(item_id: str | None = None) -> dict[str, Any]:
    run_id = _run_start("Meu Pluggy")
    try:
        client_id = get_secret("pluggy_client_id") or ""
        client_secret = get_secret("pluggy_client_secret") or ""
        chosen_item_id = (item_id or get_setting("pluggy_item_id")).strip()
        if not chosen_item_id:
            raise PluggyError("Informe o Item ID proxy do Meu Pluggy nas configurações.")
        client = PluggyClient(client_id, client_secret)
        bundle = client.collect(chosen_item_id)
        for investment in bundle.investments:
            inactive = str(investment.get("status") or "").upper() in {"INACTIVE", "CLOSED", "REDEEMED"}
            if _is_supported_candidate(investment) and (
                _investment_ticker(investment) is None or (investment.get("quantity") is None and not inactive)
            ):
                bundle.positions_complete = False
                bundle.errors.append("Um ativo listado veio sem ticker ou quantidade; posições anteriores foram preservadas.")
        has_previous_listed_positions = bool(rows(
            "SELECT 1 FROM v_latest_position_per_account ps "
            "JOIN financial_account a ON a.id = ps.account_id "
            "WHERE a.provider = 'pluggy' AND a.external_key = ? AND ps.source = 'pluggy' "
            "AND ps.quantity_micros > 0 LIMIT 1",
            (f"item:{chosen_item_id}:investments",),
        ))
        has_returned_listed_positions = any(
            _is_supported_candidate(investment)
            and _investment_ticker(investment) is not None
            and (
                investment.get("quantity") is not None
                or str(investment.get("status") or "").upper() in {"INACTIVE", "CLOSED", "REDEEMED"}
            )
            for investment in bundle.investments
        )
        if bundle.positions_complete and has_previous_listed_positions and not has_returned_listed_positions:
            bundle.positions_complete = False
            bundle.errors.append(
                "A origem não retornou ativos listados apesar de existirem posições anteriores; elas foram preservadas."
            )
        with transaction() as connection:
            records_read, records_written = _write_pluggy_data(connection, chosen_item_id, bundle, run_id)
        status = "partial" if bundle.errors or not bundle.positions_complete else "success"
        message = "Sincronização Pluggy concluída."
        external_updated_at = next(
            (
                str(bundle.item[field])
                for field in ("lastUpdatedAt", "dataUpdatedAt", "updatedAt")
                if bundle.item.get(field)
            ),
            None,
        )
        if bundle.errors:
            message = "Dados válidos foram salvos; " + " ".join(bundle.errors[:3])
        elif not bundle.positions_complete:
            message = "Sincronização parcial; posições anteriores foram preservadas."
        _run_finish(run_id, status, records_read, records_written, message, external_updated_at)
        return {"status": status, "records_read": records_read, "records_written": records_written, "message": message}
    except (PluggyError, RuntimeError) as exc:
        message = str(exc)[:500]
        _run_finish(run_id, "failed", 0, 0, message)
        raise SyncError(message) from exc
    except Exception as exc:
        message = "Falha inesperada na sincronização Pluggy. Confira as configurações e tente novamente."
        _run_finish(run_id, "failed", 0, 0, message)
        raise SyncError(message) from exc


def sync_daily_quotes() -> dict[str, Any]:
    run_id = _run_start("brapi — fechamento diário")
    positions = rows(
        "SELECT ticker FROM v_portfolio_positions WHERE quantity_micros > 0 ORDER BY ticker"
    )
    tickers = [str(row["ticker"]) for row in positions]
    if not tickers:
        message = "Não há posições para atualizar cotações."
        _run_finish(run_id, "success", 0, 0, message)
        return {"status": "success", "updated": 0, "errors": [], "message": message}
    if len(tickers) > 200:
        tickers = tickers[:200]
        truncated = True
    else:
        truncated = False
    try:
        token = get_secret("brapi_token")
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "Não foi possível acessar o token no Credential Manager do Windows."
        _run_finish(run_id, "failed", 0, 0, message)
        raise SyncError(message) from exc
    fetched: list[tuple[str, str, int]] = []
    errors: list[str] = []
    for ticker in tickers:
        try:
            trade_date, close_cents = latest_daily_close(ticker, token)
            fetched.append((ticker, trade_date, close_cents))
        except BrapiError as exc:
            errors.append(str(exc))
        except Exception:
            errors.append(f"{ticker}: falha inesperada ao processar a cotação.")
    if truncated:
        errors.append("Foram consultados os primeiros 200 ativos; limite local atingido.")
    try:
        with transaction() as connection:
            for ticker, trade_date, close_cents in fetched:
                instrument_id = int(
                    connection.execute("SELECT id FROM instrument WHERE ticker = ?", (ticker,)).fetchone()[0]
                )
                connection.execute(
                    "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
                    "VALUES (?, ?, ?, 'brapi') "
                    "ON CONFLICT(instrument_id, trade_date, provider) DO UPDATE SET "
                    "close_cents = excluded.close_cents, fetched_at = CURRENT_TIMESTAMP",
                    (instrument_id, trade_date, close_cents),
                )
    except Exception as exc:
        message = "Falha ao gravar os fechamentos diários no SQLite; os preços anteriores foram preservados."
        _run_finish(run_id, "failed", len(tickers), 0, message)
        raise SyncError(message) from exc
    if errors and fetched:
        status = "partial"
    elif errors:
        status = "failed"
    else:
        status = "success"
    message = f"{len(fetched)} fechamento(s) atualizado(s)."
    if errors:
        message += " " + " ".join(errors[:4])
    _run_finish(run_id, status, len(tickers), len(fetched), message)
    return {"status": status, "updated": len(fetched), "errors": errors, "message": message}


def auto_daily_quotes_once() -> None:
    if get_setting("daily_quotes_enabled", "1") != "1":
        return
    local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    if (local_now.hour, local_now.minute) < (19, 30):
        return
    day_key = local_now.date().isoformat()
    if get_setting("last_auto_quotes_date") == day_key:
        return
    if not rows("SELECT 1 FROM v_portfolio_positions WHERE quantity_micros > 0 LIMIT 1"):
        return
    set_setting("last_auto_quotes_date", day_key)
    try:
        sync_daily_quotes()
    except Exception:
        # O painel registra e apresenta o estado das sincronizações; a rotina nunca encerra o servidor.
        return


def quote_scheduler(stop_event: threading.Event) -> None:
    while not stop_event.wait(60):
        auto_daily_quotes_once()
