from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.db import get_setting, rows, set_setting, transaction
from app.providers.bcb import BcbError, cdi_daily_rates
from app.providers.brapi import BrapiError, daily_history
from app.providers.pluggy import PluggyClient, PluggyData, PluggyError
from app.security import get_secret
from app.services.accounts import link_accounts
from app.services.categories import PLUGGY_CATEGORIES, categorize
from app.services.fundamentals import auto_sync_weekly
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


INACTIVE_STATUSES = {"INACTIVE", "CLOSED", "REDEEMED"}

# Código de compensação → nome curto. O Meu Pluggy é um conector só ("MeuPluggy"), então a instituição
# de cada item é deduzida das contas dele.
BANK_CODES = {
    "001": "Banco do Brasil", "033": "Santander", "077": "Inter", "102": "XP", "104": "Caixa", "208": "BTG Pactual",
    "212": "Original", "237": "Bradesco", "260": "Nubank", "290": "PagBank", "323": "Mercado Pago", "336": "C6 Bank",
    "341": "Itaú", "380": "PicPay", "655": "Neon", "748": "Sicredi", "756": "Sicoob",
}
INSTITUTION_HINTS = (
    ("nu pagamentos", "Nubank"), ("nubank", "Nubank"), ("nu financeira", "Nubank"), ("itau", "Itaú"),
    ("unibanco", "Itaú"), ("bradesco", "Bradesco"), ("santander", "Santander"), ("banco do brasil", "Banco do Brasil"),
    ("caixa economica", "Caixa"), ("banco inter", "Inter"), ("c6", "C6 Bank"), ("btg", "BTG Pactual"),
    ("xp investimentos", "XP"), ("picpay", "PicPay"), ("mercado pago", "Mercado Pago"), ("pagseguro", "PagBank"),
)
GENERIC_CONNECTORS = {"meupluggy", "meu pluggy", "open finance", ""}


def _plain(text: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _hinted_institution(text: object) -> str | None:
    plain = _plain(text)
    return next((name for hint, name in INSTITUTION_HINTS if hint in plain), None)


def detect_institution(payload: PluggyData) -> str:
    """Nome curto da instituição do item: conector direto, código do banco da conta ou nome da conta."""
    connector = payload.item.get("connector")
    connector_name = str(connector.get("name") or "") if isinstance(connector, dict) else str(connector or "")
    if _plain(connector_name) not in GENERIC_CONNECTORS:
        return _hinted_institution(connector_name) or connector_name.strip()[:40]
    ordered = sorted(payload.accounts, key=lambda a: str(a.get("type") or "").upper() != "BANK")
    for account in ordered:
        bank_data = account.get("bankData") if isinstance(account.get("bankData"), dict) else {}
        code = str(bank_data.get("transferNumber") or "").split("/")[0].strip()
        if code.isdigit() and code.zfill(3) in BANK_CODES:
            return BANK_CODES[code.zfill(3)]
        for field in ("name", "marketingName"):
            found = _hinted_institution(account.get(field))
            if found:
                return found
    for investment in payload.investments:
        found = _hinted_institution(investment.get("issuer")) or _hinted_institution(investment.get("institution"))
        if found:
            return found
    return "Open Finance"


def investment_account_name(institution: str) -> str:
    """A custódia Nubank mantém o apelido usado pela B3 e pelos CSVs, para consolidar sem contar em dobro."""
    return "Nubank / NuInvest" if institution == "Nubank" else f"{institution} / Investimentos"


def _asset_class(investment: dict[str, Any]) -> str:
    subtype = str(investment.get("subtype") or "").upper()
    kind = str(investment.get("type") or "").upper()
    if "BDR" in subtype:
        return "BDR"
    if "FII" in subtype or "REAL_ESTATE" in subtype:
        return "FII"
    if kind == "ETF" or subtype == "ETF":
        return "ETF"
    return "Ação"


def _is_supported_candidate(investment: dict[str, Any]) -> bool:
    """Ativo listado (ação, FII, ETF, BDR). Fundos e previdência com "STOCK" no subtipo não entram."""
    kind = str(investment.get("type") or "").upper()
    subtype = str(investment.get("subtype") or "").upper()
    if kind in {"EQUITY", "ETF"}:
        return True
    if kind in {"MUTUAL_FUND", "SECURITY", "FIXED_INCOME", "COE", "OTHER"}:
        return False
    return subtype in {"STOCK", "ETF", "BDR", "REAL_ESTATE_FUND", "FII"}


def _investment_ticker(investment: dict[str, Any]) -> str | None:
    for field in ("ticker", "symbol", "code"):
        ticker = safe_ticker(investment.get(field))
        if ticker:
            return ticker
    return None


def _fixed_income_type(investment: dict[str, Any]) -> str:
    subtype = str(investment.get("subtype") or "").upper()
    kind = str(investment.get("type") or "").upper()
    name = str(investment.get("name") or "").upper()
    if kind == "SECURITY" or any(key in subtype for key in ("RETIREMENT", "PGBL", "VGBL", "PENSION")):
        return "Previdência"
    for label, keys in (
        ("Previdência", ("PREVID", "PGBL", "VGBL")), ("Caixinha", ("RDB", "CAIXINHA")), ("CDB", ("CDB",)),
        ("LCI", ("LCI",)), ("LCA", ("LCA",)), ("Tesouro", ("TREASURY", "TESOURO")), ("CRI/CRA", ("CRI", "CRA")),
        ("Debênture", ("DEBENTURE",)), ("Fundo", ("FUND",)), ("COE", ("COE",)),
    ):
        if any(key in subtype or key in name or key in kind for key in keys):
            return label
    return "Renda fixa" if kind == "FIXED_INCOME" else "Outros"


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _rate_label(investment: dict[str, Any]) -> str | None:
    """'IPCA' + '7,63%' ou 'CDI' + '115%': a tela mostra indexador e taxa lado a lado."""
    rate_type = str(investment.get("rateType") or "").upper()
    rate = _number(investment.get("rate"))
    fixed = _number(investment.get("fixedAnnualRate"))
    if rate_type in {"IPCA", "IGPM", "INPC"} and fixed is not None:
        return f"+ {fixed:.2f}%".replace(".", ",")
    if rate is not None:
        return f"{rate:g}%".replace(".", ",")
    if fixed is not None:
        return f"{fixed:.2f}% a.a.".replace(".", ",")
    return None


def _document(party: object) -> str:
    if not isinstance(party, dict):
        return ""
    document = party.get("documentNumber")
    value = document.get("value") if isinstance(document, dict) else document
    return re.sub(r"\D", "", str(value or ""))


def _source_category(item: dict[str, Any]) -> str | None:
    """Mesmo CPF/CNPJ de pagador e recebedor é transferência própria, independente do rótulo da Pluggy."""
    payment = item.get("paymentData") if isinstance(item.get("paymentData"), dict) else {}
    payer, receiver = _document(payment.get("payer")), _document(payment.get("receiver"))
    if payer and payer == receiver:
        return "Transferência própria"
    return PLUGGY_CATEGORIES.get(str(item.get("category") or ""))


def _foreign_currency(item: dict[str, Any], account_currency: str) -> str | None:
    currency = str(item.get("currencyCode") or account_currency).upper()
    return currency if currency != account_currency else None


def _account_amount(item: dict[str, Any]) -> object:
    """Compra em moeda estrangeira: amount vem na moeda original (ex.: US$ 21,36) e amountInAccountCurrency
    traz o valor em reais convertido na data da compra, que é o que entra na fatura."""
    converted = item.get("amountInAccountCurrency")
    return converted if converted is not None else item.get("amount")


def _signed_amount(item: dict[str, Any], account_type: str) -> int:
    """Saída negativa, entrada positiva em qualquer conta.

    Na conta a Pluggy já manda o sinal; no cartão manda compra positiva e pagamento/estorno negativo.
    O campo type (DEBIT/CREDIT) resolve os dois casos.
    """
    raw = api_amount_to_cents(_account_amount(item))
    direction = str(item.get("type") or "").upper()
    if direction == "DEBIT":
        return -abs(raw)
    if direction == "CREDIT":
        return abs(raw)
    return -raw if account_type == "CREDIT" else raw


def _signed_event_quantity(event_type: str, raw_quantity: object) -> int:
    quantity = api_quantity_to_micros(raw_quantity)
    normalized = event_type.upper()
    if normalized in {"SELL", "TRANSFER_OUT"}:
        return -abs(quantity)
    if normalized in {"BUY", "TRANSFER_IN", "OPENING", "SPLIT"}:
        return abs(quantity)
    return 0


def _write_pluggy_data(
    connection, item_id: str, payload: PluggyData, run_id: int, institution: str
) -> tuple[int, int]:
    written = 0
    unconverted = 0
    records_read = len(payload.accounts) + len(payload.investments)
    snapshot_day = _day(
        payload.item.get("lastUpdatedAt") or payload.item.get("updatedAt") or payload.item.get("dataUpdatedAt")
    )

    for account in payload.accounts:
        external_id = str(account.get("id") or "")
        if not external_id:
            continue
        external_key = f"item:{item_id}:account:{external_id}"
        currency = str(account.get("currencyCode") or "BRL").upper()
        account_type = str(account.get("type") or "BANK").upper()
        account_digits = re.sub(r"\D", "", str(account.get("number") or ""))
        account_suffix = account_digits[-4:]
        base_name = {"BANK": institution, "CREDIT": f"{institution} Cartão"}.get(account_type)
        if base_name:
            account_name = f"{base_name} ••••{account_suffix}" if account_suffix else base_name
        else:
            account_name = f"{institution} / {account.get('subtype') or account_type}"
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
        credit_data = account.get("creditData") if isinstance(account.get("creditData"), dict) else {}
        if account_type == "CREDIT" and credit_data:
            limit = credit_data.get("creditLimit")
            available = credit_data.get("availableCreditLimit")
            connection.execute(
                "UPDATE financial_account SET credit_limit_cents = ?, available_limit_cents = ? WHERE id = ?",
                (api_amount_to_cents(limit) if limit is not None else None,
                 api_amount_to_cents(available) if available is not None else None, account_id),
            )
        if account.get("balance") is not None:
            as_of = _day(account.get("updatedAt"), date.fromisoformat(snapshot_day))
            balance_cents = api_amount_to_cents(account.get("balance"))
            if account_type == "CREDIT":
                balance_cents = -abs(balance_cents)
            connection.execute(
                "INSERT INTO account_balance_snapshot(account_id, sync_run_id, source, as_of_date, balance_cents) "
                "VALUES (?, ?, 'pluggy', ?, ?) "
                "ON CONFLICT(account_id, source, as_of_date) DO UPDATE SET "
                "balance_cents = excluded.balance_cents, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (account_id, run_id, as_of, balance_cents),
            )
            written += 1
        transactions = payload.transactions_by_account.get(external_id, [])
        records_read += len(transactions)
        for item in transactions:
            source_id = str(item.get("id") or "").strip()
            transaction_day = _day(item.get("date"), date.fromisoformat(snapshot_day))
            description = str(item.get("description") or item.get("descriptionRaw") or "Movimentação Open Finance")[:250]
            signed_amount = _signed_amount(item, account_type)
            raw_status = str(item.get("status") or "UNKNOWN").upper()
            transaction_status = raw_status if raw_status in {"POSTED", "PENDING"} else "UNKNOWN"
            if not source_id:
                source_id = _sha(f"{external_id}|{transaction_day}|{description}|{signed_amount}")
            transaction_key = f"{external_id}:{source_id}"
            credit_meta = item.get("creditCardMetadata") if isinstance(item.get("creditCardMetadata"), dict) else {}
            statement_ref = str(credit_meta.get("billId") or "")[:64] or None
            original_currency = _foreign_currency(item, currency)
            original_amount = None
            if original_currency:
                original_amount = abs(api_amount_to_cents(item.get("amount"))) * (1 if signed_amount >= 0 else -1)
                if item.get("amountInAccountCurrency") is None:
                    unconverted += 1
            connection.execute(
                "INSERT INTO cash_transaction(account_id, sync_run_id, source, external_id, transaction_date, description, "
                "amount_cents, status, currency, category, statement_ref, original_currency, original_amount_cents) "
                "VALUES (?, ?, 'pluggy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, external_id) DO UPDATE SET transaction_date = excluded.transaction_date, "
                "description = excluded.description, amount_cents = excluded.amount_cents, status = excluded.status, "
                "currency = excluded.currency, sync_run_id = excluded.sync_run_id, category = excluded.category, "
                "original_currency = excluded.original_currency, original_amount_cents = excluded.original_amount_cents",
                (account_id, run_id, transaction_key, transaction_day, description, signed_amount, transaction_status,
                 currency, categorize(description, _source_category(item)), statement_ref,
                 original_currency, original_amount),
            )
            written += 1

    investment_account_key = f"item:{item_id}:investments"
    investment_alias = investment_account_name(institution)
    connection.execute(
        "INSERT INTO financial_account(institution, account_name, account_type, currency, provider, external_key) "
        "VALUES (?, ?, 'INVESTMENT', 'BRL', 'pluggy', ?) "
        "ON CONFLICT(provider, external_key) DO UPDATE SET institution = excluded.institution, account_name = excluded.account_name",
        (institution, investment_alias, investment_account_key),
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
        "SELECT id FROM financial_account WHERE provider = 'manual' AND account_name = ? LIMIT 1", (investment_alias,)
    ).fetchone()
    listed = [investment for investment in payload.investments if _is_supported_candidate(investment)]
    if payload.positions_complete:
        for investment in listed:
            ticker = _investment_ticker(investment)
            quantity = investment.get("quantity")
            inactive = str(investment.get("status") or "").upper() in INACTIVE_STATUSES
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
            connection.execute(
                "INSERT INTO position_snapshot(account_id, instrument_id, sync_run_id, source, as_of_date, quantity_micros) "
                "VALUES (?, ?, ?, 'pluggy', ?, ?) "
                "ON CONFLICT(account_id, instrument_id, source, as_of_date) DO UPDATE SET "
                "quantity_micros = excluded.quantity_micros, sync_run_id = excluded.sync_run_id, imported_at = CURRENT_TIMESTAMP",
                (investment_account_id, instrument_id, run_id, snapshot_day, quantity_micros),
            )
            written += 1

    current_products: set[str] = set()
    for investment in payload.investments:
        if _is_supported_candidate(investment):
            continue
        investment_id = str(investment.get("id") or "")
        net = investment.get("balance")
        if net is None:
            net = investment.get("amountWithdrawal")
        # 'amount' é o valor bruto; 'balance'/'amountWithdrawal' já descontam IR e taxas.
        gross = investment.get("amount") if investment.get("amount") is not None else net
        if not investment_id or gross is None:
            continue
        product_key = f"pluggy:{item_id}:{investment_id}"
        inactive = str(investment.get("status") or "").upper() in INACTIVE_STATUSES
        name = str(investment.get("name") or investment.get("subtype") or "Investimento")[:120]
        purchase = investment.get("purchaseDate") or investment.get("issueDate")
        connection.execute(
            "INSERT INTO fixed_income_snapshot(account_id, sync_run_id, source, product_key, product_type, name, issuer, "
            "indexer, rate, maturity_date, as_of_date, invested_cents, gross_value_cents, net_value_cents, purchase_date) "
            "VALUES (?, ?, 'pluggy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(product_key, source, as_of_date) DO UPDATE SET account_id = excluded.account_id, "
            "sync_run_id = excluded.sync_run_id, product_type = excluded.product_type, name = excluded.name, "
            "indexer = excluded.indexer, rate = excluded.rate, invested_cents = excluded.invested_cents, "
            "gross_value_cents = excluded.gross_value_cents, net_value_cents = excluded.net_value_cents, "
            "purchase_date = excluded.purchase_date, imported_at = CURRENT_TIMESTAMP",
            (
                investment_account_id, run_id, product_key, _fixed_income_type(investment), name,
                str(investment.get("issuer") or "") or None,
                str(investment.get("rateType") or "") or None,
                _rate_label(investment),
                _day(investment.get("dueDate")) if investment.get("dueDate") else None,
                snapshot_day,
                api_amount_to_cents(investment.get("amountOriginal")) if investment.get("amountOriginal") is not None else None,
                0 if inactive else api_amount_to_cents(gross),
                0 if inactive else (api_amount_to_cents(net) if net is not None else None),
                _day(purchase) if purchase else None,
            ),
        )
        current_products.add(product_key)
        written += 1
    if payload.positions_complete:
        for row in connection.execute(
            "SELECT DISTINCT product_key, product_type, name FROM fixed_income_snapshot "
            "WHERE source = 'pluggy' AND product_key LIKE ?", (f"pluggy:{item_id}:%",),
        ).fetchall():
            if row["product_key"] in current_products:
                continue
            connection.execute(
                "INSERT OR IGNORE INTO fixed_income_snapshot(account_id, sync_run_id, source, product_key, product_type, "
                "name, as_of_date, gross_value_cents) VALUES (?, ?, 'pluggy', ?, ?, ?, ?, 0)",
                (investment_account_id, run_id, row["product_key"], row["product_type"], row["name"], snapshot_day),
            )

    for investment in listed:
        ticker = _investment_ticker(investment)
        investment_id = str(investment.get("id") or "")
        if ticker is None or not investment_id:
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
    link_accounts(connection)
    if unconverted:
        payload.errors.append(
            f"{unconverted} compra(s) em moeda estrangeira vieram sem o valor em reais e ficaram no valor original."
        )
    return records_read, written


UUID_PATTERN = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.IGNORECASE)


def parse_item_ids(text: str | None) -> tuple[list[str], list[str]]:
    """Extrai Item IDs de qualquer texto colado: vírgula, ponto e vírgula, espaço ou quebra de linha,
    aspas, maiúsculas e até a URL do dashboard. Devolve (ids válidos sem repetição, trechos ignorados)."""
    valid: list[str] = []
    ignored: list[str] = []
    for token in re.split(r"[\s,;|]+", text or ""):
        token = token.strip("\"'`[](){}<>.")
        if not token:
            continue
        found = UUID_PATTERN.findall(token)
        if not found:
            ignored.append(token[:40])
        for value in found:
            normalized = str(UUID(value))
            if normalized not in valid:
                valid.append(normalized)
    return valid, ignored


def pluggy_item_ids() -> list[str]:
    """Itens configurados (a migração 003 trouxe o Item ID único das versões anteriores)."""
    return parse_item_ids(get_setting("pluggy_item_ids"))[0]


def _check_listed_positions(item_id: str, bundle: PluggyData) -> None:
    for investment in bundle.investments:
        inactive = str(investment.get("status") or "").upper() in INACTIVE_STATUSES
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
        (f"item:{item_id}:investments",),
    ))
    has_returned_listed_positions = any(
        _is_supported_candidate(investment)
        and _investment_ticker(investment) is not None
        and (
            investment.get("quantity") is not None
            or str(investment.get("status") or "").upper() in INACTIVE_STATUSES
        )
        for investment in bundle.investments
    )
    if bundle.positions_complete and has_previous_listed_positions and not has_returned_listed_positions:
        bundle.positions_complete = False
        bundle.errors.append(
            "A origem não retornou ativos listados apesar de existirem posições anteriores; elas foram preservadas."
        )


def _sync_item(client: PluggyClient, item_id: str) -> dict[str, Any]:
    run_id = _run_start("Meu Pluggy")
    try:
        bundle = client.collect(item_id)
        normalized_item_id = str(bundle.item.get("id") or item_id).strip().lower()
        institution = detect_institution(bundle)
        _check_listed_positions(normalized_item_id, bundle)
        with transaction() as connection:
            connection.execute("UPDATE sync_run SET source = ? WHERE id = ?", (f"Meu Pluggy · {institution}", run_id))
            records_read, records_written = _write_pluggy_data(
                connection, normalized_item_id, bundle, run_id, institution
            )
        status = "partial" if bundle.errors or not bundle.positions_complete else "success"
        message = f"{institution}: sincronização concluída."
        external_updated_at = next(
            (
                str(bundle.item[field])
                for field in ("lastUpdatedAt", "dataUpdatedAt", "updatedAt")
                if bundle.item.get(field)
            ),
            None,
        )
        if bundle.errors:
            message = f"{institution}: dados válidos foram salvos; " + " ".join(bundle.errors[:3])
        elif not bundle.positions_complete:
            message = f"{institution}: sincronização parcial; posições anteriores foram preservadas."
        _run_finish(run_id, status, records_read, records_written, message, external_updated_at)
        return {"status": status, "records_read": records_read, "records_written": records_written, "message": message}
    except (PluggyError, RuntimeError) as exc:
        message = f"Item {item_id[:8]}…: {str(exc)[:450]}"
        _run_finish(run_id, "failed", 0, 0, message)
        return {"status": "failed", "records_read": 0, "records_written": 0, "message": message}
    except Exception:
        message = f"Item {item_id[:8]}…: falha inesperada na sincronização Pluggy."
        _run_finish(run_id, "failed", 0, 0, message)
        return {"status": "failed", "records_read": 0, "records_written": 0, "message": message}


def sync_pluggy(item_id: str | None = None) -> dict[str, Any]:
    """Sincroniza cada item configurado (ex.: Nubank e Itaú) com uma sessão só; um item com falha não barra os demais."""
    item_ids = [item_id] if item_id else pluggy_item_ids()
    if not item_ids:
        run_id = _run_start("Meu Pluggy")
        message = "Informe ao menos um Item ID do Meu Pluggy nas configurações."
        _run_finish(run_id, "failed", 0, 0, message)
        raise SyncError(message)
    try:
        client = PluggyClient(get_secret("pluggy_client_id") or "", get_secret("pluggy_client_secret") or "")
    except (PluggyError, RuntimeError) as exc:
        run_id = _run_start("Meu Pluggy")
        _run_finish(run_id, "failed", 0, 0, str(exc)[:500])
        raise SyncError(str(exc)[:500]) from exc
    with client:
        results = [_sync_item(client, value) for value in item_ids]
    failed = [r for r in results if r["status"] == "failed"]
    if len(failed) == len(results):
        raise SyncError(" ".join(r["message"] for r in failed)[:500])
    status = "partial" if failed or any(r["status"] == "partial" for r in results) else "success"
    return {
        "status": status,
        "records_read": sum(r["records_read"] for r in results),
        "records_written": sum(r["records_written"] for r in results),
        "message": " ".join(r["message"] for r in results)[:500],
    }


def _quote_range(ticker: str) -> str:
    """Primeira coleta de um ativo busca 1 ano; depois, apenas o último mês."""
    known = rows(
        "SELECT COUNT(*) AS n FROM daily_quote dq JOIN instrument i ON i.id = dq.instrument_id "
        "WHERE i.ticker = ? AND dq.provider = 'brapi'", (ticker,),
    )
    return "1mo" if known and known[0]["n"] >= 15 else "1y"


def _fetch_history(ticker: str, token: str | None) -> list[tuple[str, int]]:
    ranges = [_quote_range(ticker)]
    if ranges[0] == "1y":
        ranges += ["3mo", "1mo"]
    last_error: BrapiError | None = None
    for period in ranges:
        try:
            return daily_history(ticker, token, period)
        except BrapiError as exc:
            last_error = exc
            if not exc.retry_shorter:
                break
    raise last_error or BrapiError(f"{ticker}: sem histórico.")


def sync_benchmarks(token: str | None) -> list[str]:
    """IBOV (brapi) e CDI (Banco Central). Falhas aqui não invalidam as cotações da carteira."""
    errors: list[str] = []
    try:
        ibov = _fetch_history("^BVSP", token)
        with transaction() as connection:
            connection.executemany(
                "INSERT INTO benchmark_quote(code, trade_date, value, provider) VALUES ('IBOV', ?, ?, 'brapi') "
                "ON CONFLICT(code, trade_date) DO UPDATE SET value = excluded.value, fetched_at = CURRENT_TIMESTAMP",
                [(day, cents / 100) for day, cents in ibov],
            )
    except BrapiError as exc:
        errors.append(f"IBOV: {exc}")
    try:
        last = rows("SELECT MAX(trade_date) AS d FROM benchmark_quote WHERE code = 'CDI'")
        cdi = cdi_daily_rates(last[0]["d"] if last and last[0]["d"] else None)
        with transaction() as connection:
            connection.executemany(
                "INSERT INTO benchmark_quote(code, trade_date, value, provider) VALUES ('CDI', ?, ?, 'bcb') "
                "ON CONFLICT(code, trade_date) DO UPDATE SET value = excluded.value, fetched_at = CURRENT_TIMESTAMP",
                cdi,
            )
    except BcbError as exc:
        errors.append(f"CDI: {exc}")
    return errors


def sync_daily_quotes() -> dict[str, Any]:
    run_id = _run_start("Mercado — cotações e índices")
    positions = rows(
        "SELECT DISTINCT i.ticker FROM instrument i "
        "WHERE i.id IN (SELECT instrument_id FROM position_snapshot) "
        "OR i.id IN (SELECT instrument_id FROM investment_event) ORDER BY i.ticker"
    )
    tickers = [str(row["ticker"]) for row in positions][:200]
    truncated = len(positions) > 200
    try:
        token = get_secret("brapi_token")
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "Não foi possível acessar o token no Credential Manager do Windows."
        _run_finish(run_id, "failed", 0, 0, message)
        raise SyncError(message) from exc
    fetched: list[tuple[str, list[tuple[str, int]]]] = []
    errors: list[str] = []
    for ticker in tickers:
        try:
            fetched.append((ticker, _fetch_history(ticker, token)))
        except BrapiError as exc:
            errors.append(str(exc))
        except Exception:
            errors.append(f"{ticker}: falha inesperada ao processar a cotação.")
    if truncated:
        errors.append("Foram consultados os primeiros 200 ativos; limite local atingido.")
    written = 0
    try:
        with transaction() as connection:
            for ticker, history in fetched:
                instrument_id = int(
                    connection.execute("SELECT id FROM instrument WHERE ticker = ?", (ticker,)).fetchone()[0]
                )
                connection.executemany(
                    "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
                    "VALUES (?, ?, ?, 'brapi') "
                    "ON CONFLICT(instrument_id, trade_date, provider) DO UPDATE SET "
                    "close_cents = excluded.close_cents, fetched_at = CURRENT_TIMESTAMP",
                    [(instrument_id, day, close) for day, close in history],
                )
                written += len(history)
    except Exception as exc:
        message = "Falha ao gravar os fechamentos no SQLite; os preços anteriores foram preservados."
        _run_finish(run_id, "failed", len(tickers), 0, message)
        raise SyncError(message) from exc
    benchmark_errors = sync_benchmarks(token)
    if errors and fetched:
        status = "partial"
    elif errors and tickers:
        status = "failed"
    else:
        status = "partial" if benchmark_errors else "success"
    message = f"{len(fetched)} ativo(s) atualizado(s), {written} fechamento(s) gravado(s)."
    if errors or benchmark_errors:
        message += " " + " ".join((errors + benchmark_errors)[:4])
    _run_finish(run_id, status, len(tickers), written, message)
    return {"status": status, "updated": len(fetched), "errors": errors + benchmark_errors, "message": message}


def auto_daily_quotes_once() -> None:
    if get_setting("daily_quotes_enabled", "1") != "1":
        return
    auto_sync_weekly()
    local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    if (local_now.hour, local_now.minute) < (19, 30):
        return
    day_key = local_now.date().isoformat()
    if get_setting("last_auto_quotes_date") == day_key:
        return
    if not rows("SELECT 1 FROM instrument LIMIT 1"):
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
