from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.services.formatting import money_to_cents


API_BASE = "https://brapi.dev/api"


class BrapiError(RuntimeError):
    """Falha externa sem incluir token ou resposta financeira no texto."""


def latest_daily_close(ticker: str, token: str | None = None) -> tuple[str, int]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(
            f"{API_BASE}/v2/stocks/historical",
            params={"symbols": ticker, "range": "1mo", "interval": "1d", "sortOrder": "asc"},
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise BrapiError(f"{ticker}: falha de rede ao consultar cotações.") from exc
    if response.status_code in (401, 403):
        raise BrapiError(f"{ticker}: o plano/token brapi não permite consultar esse ativo.")
    if response.status_code == 429:
        raise BrapiError(f"{ticker}: limite de consultas brapi atingido.")
    if response.status_code != 200:
        raise BrapiError(f"{ticker}: brapi respondeu com HTTP {response.status_code}.")
    try:
        payload = response.json()
        results = payload.get("results", [])
        if not results:
            raise BrapiError(f"{ticker}: ativo sem histórico disponível na brapi.")
        returned_symbol = str(results[0].get("symbol") or ticker).upper()
        if returned_symbol != ticker.upper():
            raise BrapiError(f"{ticker}: código mudou para {returned_symbol}; atualize o cadastro do ativo antes de importar esse preço.")
        history = results[0].get("data", {}).get("historicalDataPrice", [])
    except (ValueError, AttributeError, TypeError) as exc:
        raise BrapiError(f"{ticker}: resposta de cotação em formato inesperado.") from exc
    if not isinstance(history, list):
        raise BrapiError(f"{ticker}: histórico diário inválido.")
    valid_rows: list[tuple[str, int]] = []
    for entry in history:
        if not isinstance(entry, dict) or entry.get("close") is None or entry.get("date") is None:
            continue
        try:
            timestamp = int(entry["date"])
            trade_date = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(
                ZoneInfo("America/Sao_Paulo")
            ).date().isoformat()
            close_cents = money_to_cents(entry["close"])
        except (ValueError, TypeError, OSError):
            continue
        if close_cents >= 0:
            valid_rows.append((trade_date, close_cents))
    if not valid_rows:
        raise BrapiError(f"{ticker}: nenhum fechamento diário válido foi recebido.")
    return max(valid_rows, key=lambda row: row[0])
