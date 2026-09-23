from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_decimal(raw: object) -> Decimal:
    value = str("" if raw is None else raw).strip().replace("R$", "").replace(" ", "")
    if not value:
        raise ValueError("Campo numérico vazio.")
    negative_parentheses = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    value = re.sub(r"[^0-9,.-]", "", value)
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Valor numérico inválido.") from exc
    if negative_parentheses:
        result = -abs(result)
    return result


def money_to_cents(raw: object) -> int:
    amount = parse_decimal(raw)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quantity_to_micros(raw: object) -> int:
    quantity = parse_decimal(raw)
    return int((quantity * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def unit_price_cents(raw: object) -> int:
    return money_to_cents(raw)


def brl(cents: int | None) -> str:
    if cents is None:
        return "—"
    value = Decimal(cents) / 100
    rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {rendered}"


def quantity(micros: int | None) -> str:
    if micros is None:
        return "—"
    value = Decimal(micros) / 1_000_000
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered or "0"
