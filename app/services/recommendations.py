"""Recomendações trimestrais do agente: mudanças na carteira atual e carteiras-modelo sugeridas.

Um conjunto por trimestre e autor (`period` como "3T26"). Reimportar o mesmo período e autor substitui o
conjunto inteiro; os trimestres anteriores ficam guardados como histórico. Formato em docs/agente-financeiro.md.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.db import rows, transaction

ACTIONS = ("comprar", "aumentar", "manter", "reduzir", "vender", "incluir")
ACTION_LABELS = {"comprar": "Comprar", "aumentar": "Aumentar", "manter": "Manter", "reduzir": "Reduzir",
                 "vender": "Vender", "incluir": "Incluir"}
REGIONS = ("nacional", "internacional")


class RecommendationError(ValueError):
    pass


def _weight(value: Any, where: str) -> float | None:
    if value is None:
        return None
    try:
        weight = float(value)
    except (TypeError, ValueError) as exc:
        raise RecommendationError(f"{where}: peso inválido ({value!r}).") from exc
    if weight > 1:  # aceita 25 como 25%
        weight /= 100
    if not 0 <= weight <= 1:
        raise RecommendationError(f"{where}: peso precisa ficar entre 0 e 100%.")
    return weight


def _item(raw: dict[str, Any], where: str, default_action: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecommendationError(f"{where}: esperado um objeto.")
    action = str(raw.get("action") or default_action or "").strip().lower()
    if action not in ACTIONS:
        raise RecommendationError(f"{where}: action deve ser {', '.join(ACTIONS)}.")
    ticker = str(raw.get("ticker") or "").strip().upper() or None
    name = str(raw.get("name") or "").strip()[:120] or None
    if not ticker and not name:
        raise RecommendationError(f"{where}: informe ticker ou name (ex.: 'Tesouro IPCA+ 2035').")
    if ticker and not re.fullmatch(r"[A-Z0-9.]{3,12}", ticker):
        raise RecommendationError(f"{where}: ticker inválido ({ticker}).")
    region = raw.get("region")
    if region is not None and region not in REGIONS:
        raise RecommendationError(f"{where}: region deve ser nacional ou internacional.")
    conviction = raw.get("conviction")
    if conviction is not None and int(conviction) not in range(1, 6):
        raise RecommendationError(f"{where}: conviction vai de 1 a 5.")
    fair = raw.get("fair_price")
    return {
        "action": action, "ticker": ticker, "name": name, "asset_class": str(raw.get("asset_class") or "")[:40] or None,
        "region": region, "target_weight": _weight(raw.get("target_weight"), where),
        "rationale": str(raw.get("rationale") or "")[:4000] or None,
        "conviction": int(conviction) if conviction is not None else None,
        "fair_price_cents": int(round(float(fair) * 100)) if fair is not None else None,
    }


def import_recommendations(payload: Any, default_author: str = "agente") -> dict[str, int]:
    if not isinstance(payload, dict):
        raise RecommendationError("Esperado um objeto JSON com period, title, changes e portfolios.")
    period = str(payload.get("period") or "").strip()
    if not re.fullmatch(r"[1-4]T\d{2}", period):
        raise RecommendationError("period deve ser o trimestre no formato 3T26.")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise RecommendationError("Informe title.")
    author = str(payload.get("author") or default_author)[:40]
    changes = [_item(c, f"changes[{i}]") for i, c in enumerate(payload.get("changes") or [], start=1)]
    portfolios = []
    for i, p in enumerate(payload.get("portfolios") or [], start=1):
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            raise RecommendationError(f"portfolios[{i}]: informe name.")
        items = [_item(x, f"portfolios[{i}].items[{j}]", "incluir") for j, x in enumerate(p.get("items") or [], start=1)]
        total = sum(x["target_weight"] or 0 for x in items)
        if items and abs(total - 1) > 0.02:
            raise RecommendationError(f"portfolios[{i}] ({p['name']}): pesos somam {total:.0%}, precisam somar 100%.")
        portfolios.append({"name": str(p["name"]).strip()[:80], "description": str(p.get("description") or "")[:2000] or None,
                           "rationale_md": str(p.get("rationale_md") or "")[:50_000] or None,
                           "risk_profile": str(p.get("risk_profile") or "")[:40] or None, "items": items})
    with transaction() as connection:
        connection.execute("DELETE FROM recommendation_set WHERE period = ? AND author = ?", (period, author))
        set_id = connection.execute(
            "INSERT INTO recommendation_set(period, title, summary, body_md, author, model, sources) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (period, title[:200], str(payload.get("summary") or "")[:3000] or None,
             str(payload.get("body_md") or "")[:200_000] or None, author, str(payload.get("model") or "")[:80] or None,
             json.dumps(payload.get("sources") or [], ensure_ascii=False)),
        ).lastrowid

        def insert(item: dict[str, Any], portfolio_id: int | None, position: int) -> None:
            connection.execute(
                "INSERT INTO recommendation_item(set_id, portfolio_id, action, ticker, name, asset_class, region, "
                "target_weight, rationale, conviction, fair_price_cents, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (set_id, portfolio_id, item["action"], item["ticker"], item["name"], item["asset_class"], item["region"],
                 item["target_weight"], item["rationale"], item["conviction"], item["fair_price_cents"], position),
            )

        for position, item in enumerate(changes):
            insert(item, None, position)
        for p in portfolios:
            portfolio_id = connection.execute(
                "INSERT INTO recommendation_portfolio(set_id, name, description, rationale_md, risk_profile) VALUES (?, ?, ?, ?, ?)",
                (set_id, p["name"], p["description"], p["rationale_md"], p["risk_profile"]),
            ).lastrowid
            for position, item in enumerate(p["items"]):
                insert(item, portfolio_id, position)
    return {"set_id": int(set_id), "changes": len(changes), "portfolios": len(portfolios)}


def history() -> list[dict[str, Any]]:
    return [dict(r) for r in rows(
        "SELECT s.id, s.period, s.title, s.summary, s.author, s.model, s.created_at, "
        "(SELECT COUNT(*) FROM recommendation_item i WHERE i.set_id = s.id AND i.portfolio_id IS NULL) AS changes, "
        "(SELECT COUNT(*) FROM recommendation_portfolio p WHERE p.set_id = s.id) AS portfolios "
        "FROM recommendation_set s ORDER BY s.created_at DESC, s.id DESC"
    )]


def get(set_id: int | None = None) -> dict[str, Any] | None:
    """Conjunto completo; sem id, o mais recente."""
    found = rows("SELECT * FROM recommendation_set WHERE id = ?", (set_id,)) if set_id else rows(
        "SELECT * FROM recommendation_set ORDER BY created_at DESC, id DESC LIMIT 1"
    )
    if not found:
        return None
    data = dict(found[0])
    try:
        data["sources"] = json.loads(data["sources"]) if data["sources"] else []
    except ValueError:
        data["sources"] = []
    items = [dict(r) for r in rows("SELECT * FROM recommendation_item WHERE set_id = ? ORDER BY position, id", (data["id"],))]
    data["changes"] = [i for i in items if i["portfolio_id"] is None]
    data["portfolios"] = []
    for p in rows("SELECT * FROM recommendation_portfolio WHERE set_id = ? ORDER BY id", (data["id"],)):
        portfolio = dict(p)
        portfolio["items"] = [i for i in items if i["portfolio_id"] == portfolio["id"]]
        data["portfolios"].append(portfolio)
    return data


def compare_with_holdings(portfolio: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    """Quanto da carteira-modelo você já tem: sobreposição de pesos (soma dos mínimos) e o que falta."""
    overlap = 0.0
    missing = []
    for item in portfolio["items"]:
        mine = weights.get(item["ticker"] or "", 0.0)
        target = item["target_weight"] or 0.0
        overlap += min(mine, target)
        if item["ticker"] and mine == 0:
            missing.append(item["ticker"])
    return {"overlap": overlap, "missing": missing}
