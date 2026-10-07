"""Cotações diárias do Yahoo Finance: reserva da brapi e fonte do histórico longo.

Endpoint público de gráficos (sem chave). Não é uma API oficial: qualquer falha vira YahooError e quem chama segue
com as outras fontes. Só recebe o código do ativo; nenhum dado do usuário sai daqui.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import httpx

from app.services.formatting import money_to_cents


API_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
B3_TZ = ZoneInfo("America/Sao_Paulo")
# Sem um User-Agent de navegador o Yahoo recusa a consulta.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Tabimoney"}


class YahooError(RuntimeError):
    """Falha externa, sem dados do usuário no texto."""


def symbol(ticker: str) -> str:
    """Código da B3 no Yahoo: ITSA4 -> ITSA4.SA; índices (^BVSP) ficam como estão."""
    ticker = ticker.upper()
    return ticker if ticker.startswith("^") or "." in ticker else ticker + ".SA"


def daily_history(ticker: str, start: date, end: date | None = None) -> list[tuple[str, int]]:
    """Fechamentos diários de start a end, em centavos e sem ajuste de desdobramento (como a brapi).

    O Yahoo devolve os preços antigos divididos pelos desdobramentos e bonificações posteriores; aqui eles
    voltam ao valor negociado no dia, que é o que combina com a quantidade de ações daquele dia.
    """
    first = int(datetime.combine(start, time(), B3_TZ).timestamp())
    last = int(datetime.combine(end or date.today(), time(23, 59), B3_TZ).timestamp())
    try:
        response = httpx.get(
            f"{API_BASE}/{symbol(ticker)}",
            params={"period1": first, "period2": last, "interval": "1d", "events": "splits"},
            headers=HEADERS, timeout=httpx.Timeout(30.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise YahooError(f"{ticker}: falha de rede ao consultar o Yahoo.") from exc
    if response.status_code == 404:
        raise YahooError(f"{ticker}: ativo não encontrado no Yahoo.")
    if response.status_code == 429:
        raise YahooError(f"{ticker}: limite de consultas do Yahoo atingido.")
    if response.status_code != 200:
        raise YahooError(f"{ticker}: Yahoo respondeu com HTTP {response.status_code}.")
    try:
        result = response.json()["chart"]["result"][0]
        stamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
        splits = [
            (int(s["date"]), float(s["numerator"]) / float(s["denominator"]))
            for s in (result.get("events") or {}).get("splits", {}).values()
            if float(s.get("numerator") or 0) > 0 and float(s.get("denominator") or 0) > 0
        ]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise YahooError(f"{ticker}: resposta do Yahoo em formato inesperado.") from exc
    by_day: dict[str, int] = {}
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        try:
            factor = 1.0
            for split_at, ratio in splits:
                if split_at > stamp:
                    factor *= ratio
            day = datetime.fromtimestamp(int(stamp), timezone.utc).astimezone(B3_TZ).date().isoformat()
            cents = money_to_cents(round(float(close) * factor, 2))
        except (ValueError, TypeError, OSError, OverflowError):
            continue
        if cents > 0:
            by_day[day] = cents
    if not by_day:
        raise YahooError(f"{ticker}: nenhum fechamento diário no Yahoo para o período.")
    return sorted(by_day.items())
