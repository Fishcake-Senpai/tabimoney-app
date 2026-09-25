from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx


# Série 12 do SGS/Banco Central: CDI diário, em % ao dia. API pública, sem chave.
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"


class BcbError(RuntimeError):
    """Falha ao consultar o Banco Central."""


def cdi_daily_rates(since: str | None = None) -> list[tuple[str, float]]:
    start = date.fromisoformat(since) + timedelta(days=1) if since else date.today() - timedelta(days=5 * 365)
    end = date.today()
    if start > end:
        return []
    try:
        response = httpx.get(
            SGS_URL,
            params={"formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": end.strftime("%d/%m/%Y")},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise BcbError("falha de rede ao consultar o Banco Central.") from exc
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise BcbError(f"Banco Central respondeu HTTP {response.status_code}.")
    try:
        return [
            (datetime.strptime(row["data"], "%d/%m/%Y").date().isoformat(), float(row["valor"]))
            for row in response.json()
        ]
    except (ValueError, KeyError, TypeError) as exc:
        raise BcbError("resposta do Banco Central em formato inesperado.") from exc
