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


CURRENCY_SYMBOLS = {"USD": "US$", "EUR": "€", "GBP": "£"}


def foreign_money(cents: int | None, currency: str | None) -> str:
    """Valor original de uma compra em moeda estrangeira, sem sinal: 'US$ 21,36'."""
    if cents is None or not currency:
        return ""
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())
    return symbol + brl(abs(cents))[2:]


def quantity(micros: int | None) -> str:
    if micros is None:
        return "—"
    value = Decimal(micros) / 1_000_000
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _br_number(value: Decimal | float, places: int) -> str:
    rendered = f"{value:,.{places}f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def brl_signed(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "+" if cents > 0 else "−" if cents < 0 else ""
    return f"{sign}R$ {_br_number(Decimal(abs(cents)) / 100, 2)}"


def brl_compact(cents: int | None) -> str:
    if cents is None:
        return "—"
    value = Decimal(cents) / 100
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}R$ {_br_number(value / 1_000_000_000, 1)} bi"
    if value >= 1_000_000:
        return f"{sign}R$ {_br_number(value / 1_000_000, 2)} mi"
    if value >= 10_000:
        return f"{sign}R$ {_br_number(value / 1_000, 1)} mil"
    return f"{sign}R$ {_br_number(value, 2)}"


def pct(value: float | None, places: int = 2, signed: bool = True) -> str:
    if value is None:
        return "—"
    number = value * 100
    sign = "+" if signed and number > 0.00001 else "−" if number < -0.00001 else ""
    return f"{sign}{_br_number(abs(number), places)}%"


def date_br(value: str | None, short: bool = False) -> str:
    if not value:
        return "—"
    text = str(value)[:10]
    try:
        year, month, day = text.split("-")
    except ValueError:
        return text
    return f"{day}/{month}" if short else f"{day}/{month}/{year}"


def multiple(value: float | None, places: int = 1) -> str:
    if value is None:
        return "—"
    return f"{_br_number(value, places)}x"


def indicator(value: float | None, kind: str) -> str:
    """Formata um indicador fundamentalista pelo tipo declarado em fundamentals.INDICATORS."""
    if value is None:
        return "—"
    if kind == "pct":
        return pct(value, 1, False) if value >= 0 else pct(value, 1)
    if kind == "x":
        return multiple(value)
    return brl(int(value * 100))


def brl_whole(cents: int | None) -> str:
    """Reais sem centavos, para tabelas densas (ex.: gasto por categoria mês a mês)."""
    if cents is None:
        return "—"
    sign = "−" if cents < 0 else ""
    return f"{sign}R$ {_br_number(Decimal(abs(cents)) / 100, 0)}"


def metric_value(value: float | None, unit: str | None) -> str:
    """Métrica livre do agente: formata pela unidade que ele declarou (fração, reais, x, dias…)."""
    if value is None:
        return "—"
    kind = (unit or "").strip().casefold()
    if kind in {"fração", "fracao", "ratio", "%", "pct", "percentual"}:
        return pct(value, 1, value < 0)
    if kind in {"r$", "reais", "brl"}:
        return brl_compact(int(round(value * 100)))
    if kind in {"x", "vezes", "múltiplo", "multiplo"}:
        return multiple(value)
    text = _br_number(value, 0 if float(value).is_integer() else 2)
    return f"{text} {unit}" if unit else text


def month_label(value: str) -> str:
    names = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    year, month = value[:7].split("-")
    return f"{names[int(month) - 1]}/{year[2:]}"


def tone(value: float | int | None) -> str:
    """Classe CSS para ganho/perda; o sinal sempre acompanha o texto."""
    if value is None or value == 0:
        return ""
    return "up" if value > 0 else "down"
