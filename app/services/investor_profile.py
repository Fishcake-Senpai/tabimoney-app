"""Perfil do investidor: horizonte e objetivo da renda variável, que guiam as análises de longo prazo.

As análises perguntam o perfil antes de começar e o guardam aqui. Como as metas, vale por titular: um titular
pode ter perfil próprio; sem ele, vale o da casa. Com mais de 12 meses, o perfil está vencido e a IA pergunta de
novo.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.db import get_setting, set_setting, transaction

SETTING_KEY = "investor_profile"
STALE_DAYS = 365
HORIZONS = {
    "menos-de-5": "menos de 5 anos",
    "5-10": "5 a 10 anos",
    "10-20": "10 a 20 anos",
    "mais-de-20": "mais de 20 anos",
}
GOALS = {
    "renda": "renda passiva",
    "crescimento": "crescimento do patrimônio",
    "os-dois": "renda e crescimento",
}


def _key(member: int | None) -> str:
    return SETTING_KEY if member is None else f"{SETTING_KEY}:{member}"


def load(member: int | None = None, today: date | None = None) -> dict[str, Any]:
    """Perfil do titular, se ele tem perfil próprio; senão, o da casa. `own` diz qual dos dois valeu."""
    raw = get_setting(_key(member)) if member is not None else ""
    try:
        data = json.loads(raw or get_setting(SETTING_KEY) or "{}")
    except ValueError:
        data = {}
    horizon, goal, updated = data.get("horizon"), data.get("goal"), data.get("updated_at")
    configured = horizon in HORIZONS and goal in GOALS
    stale = False
    if configured and updated:
        try:
            stale = ((today or date.today()) - date.fromisoformat(updated)).days > STALE_DAYS
        except ValueError:
            stale = True
    return {
        "configured": configured, "horizon": horizon if configured else None, "goal": goal if configured else None,
        "horizon_label": HORIZONS.get(horizon) if configured else None, "goal_label": GOALS.get(goal) if configured else None,
        "updated_at": updated if configured else None, "stale": stale,
        "member": member, "own": member is None or bool(raw),
    }


def save(horizon: str, goal: str, member: int | None = None, today: date | None = None) -> dict[str, Any]:
    if horizon not in HORIZONS:
        raise ValueError(f"Horizonte inválido: {horizon}. Use {', '.join(HORIZONS)}.")
    if goal not in GOALS:
        raise ValueError(f"Objetivo inválido: {goal}. Use {', '.join(GOALS)}.")
    data = {"horizon": horizon, "goal": goal, "updated_at": (today or date.today()).isoformat()}
    set_setting(_key(member), json.dumps(data))
    return load(member, today)


def clear(member: int) -> None:
    """Apaga o perfil próprio do titular: a visão dele volta a usar o da casa."""
    with transaction() as connection:
        connection.execute("DELETE FROM app_setting WHERE key = ?", (_key(member),))
