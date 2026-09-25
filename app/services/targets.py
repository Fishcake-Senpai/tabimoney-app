"""Metas de alocação e para onde vai o próximo aporte.

Como o patrimônio é dividido:
- Reserva de emergência: meta em reais, formada pelo caixa em conta já descontada a fatura em aberto.
  O caixa que passa da meta rende CDI e conta como renda fixa.
- Investível (fora a reserva) = renda fixa + renda variável; as metas em % valem sobre ele.
  A renda fixa inclui títulos, caixinhas, o caixa excedente e, se o usuário quiser, a previdência.
- A renda variável se divide em nacional e internacional. BDRs e ETFs de índice externo são internacionais,
  e o usuário pode corrigir ativo por ativo.

Aporte sem vender: primeiro completa a reserva; depois distribui o que sobra entre as classes que estão
abaixo da meta, na proporção do que falta; se o aporte cobre tudo, o excesso segue as próprias metas.
"""
from __future__ import annotations

import json
from typing import Any

from app.db import get_setting, rows, set_setting, transaction
from app.services.formatting import brl

SETTING_KEY = "allocation_targets"
DRIFT_ALERT = 0.05  # 5 p.p. fora da meta gera aviso

# ETFs listados na B3 que replicam índices ou ativos de fora do Brasil (inclui cripto, cotada em dólar).
INTERNATIONAL_ETFS = {
    "IVVB11", "SPXI11", "SPXB11", "NASD11", "WRLD11", "ACWI11", "EURP11", "XINA11", "ASIA11", "EMEG11", "TECK11",
    "USAL11", "BNDX11", "GOLD11", "QBTC11", "QETH11", "HASH11", "BITH11", "ETHE11", "BITI11", "NDIV11", "SMAC11",
    "IBOB11", "USTK11", "JOGO11", "FOOD11", "WEB311", "QDFI11", "DEFI11", "META11", "ESGE11", "ALUG11", "SPYI11",
}
BUCKETS = {
    "reserve": "Reserva de emergência",
    "fixed": "Renda fixa",
    "equity_br": "Renda variável nacional",
    "equity_intl": "Renda variável internacional",
}


def load() -> dict[str, Any]:
    try:
        data = json.loads(get_setting(SETTING_KEY) or "{}")
    except ValueError:
        data = {}
    return {
        "reserve_cents": data.get("reserve_cents"), "fixed_pct": data.get("fixed_pct"),
        "equity_pct": data.get("equity_pct"), "intl_pct": data.get("intl_pct"),
        "pension_in_fixed": data.get("pension_in_fixed", True),
    }


def save(reserve_cents: int | None, fixed_pct: float | None, equity_pct: float | None, intl_pct: float | None,
         pension_in_fixed: bool = True) -> dict[str, Any]:
    """Percentuais como fração (0.4 = 40%). Renda fixa + variável precisa fechar 100%; um lado vazio é o complemento."""
    if reserve_cents is not None and reserve_cents < 0:
        raise ValueError("A reserva de emergência não pode ser negativa.")
    for label, value in (("renda fixa", fixed_pct), ("renda variável", equity_pct), ("internacional", intl_pct)):
        if value is not None and not 0 <= value <= 1:
            raise ValueError(f"A meta de {label} precisa ficar entre 0% e 100%.")
    if fixed_pct is None and equity_pct is not None:
        fixed_pct = 1 - equity_pct
    elif equity_pct is None and fixed_pct is not None:
        equity_pct = 1 - fixed_pct
    if fixed_pct is not None and equity_pct is not None and abs(fixed_pct + equity_pct - 1) > 0.005:
        raise ValueError(
            f"Renda fixa ({_pp(fixed_pct)}%) + renda variável ({_pp(equity_pct)}%) precisa somar 100%."
        )
    data = {"reserve_cents": reserve_cents, "fixed_pct": fixed_pct, "equity_pct": equity_pct,
            "intl_pct": intl_pct, "pension_in_fixed": bool(pension_in_fixed)}
    set_setting(SETTING_KEY, json.dumps(data))
    return data


def auto_region(ticker: str, asset_class: str | None) -> str:
    if (asset_class or "").upper() == "BDR" or ticker.upper() in INTERNATIONAL_ETFS or ticker.upper().endswith(("34", "35", "39")):
        return "internacional"
    return "nacional"


def regions() -> dict[int, dict[str, Any]]:
    return {
        int(r["id"]): {"ticker": r["ticker"], "region": r["region"] or auto_region(r["ticker"], r["asset_class"]),
                       "manual": r["region"] is not None}
        for r in rows("SELECT id, ticker, asset_class, region FROM instrument")
    }


def set_region(ticker: str, region: str | None) -> None:
    if region not in (None, "", "nacional", "internacional"):
        raise ValueError("Região deve ser nacional ou internacional.")
    with transaction() as connection:
        cursor = connection.execute("UPDATE instrument SET region = ? WHERE ticker = ?", (region or None, ticker.upper()))
        if cursor.rowcount == 0:
            raise ValueError(f"{ticker} não está cadastrado.")


def snapshot(book, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Valores atuais por classe, metas em reais e desvios."""
    targets = load()
    region_of = regions()
    cash = book.cash_at(book.today)
    card_debt = -book.card_debt_at(book.today)
    free_cash = cash - card_debt
    reserve_target = targets["reserve_cents"]
    reserve = min(max(free_cash, 0), reserve_target) if reserve_target is not None else 0
    excess_cash = max(free_cash - reserve, 0)
    fixed_products = sum(p["gross"] for p in book.fixed_income())
    pension = book.pension_at(book.today)
    fixed = fixed_products + excess_cash + (pension if targets["pension_in_fixed"] else 0)
    equity_br = equity_intl = 0
    holdings = []
    for a in assets:
        if a["qty"] <= 0 or not a["value"]:
            continue
        region = region_of.get(a["iid"], {}).get("region", "nacional")
        if region == "internacional":
            equity_intl += a["value"]
        else:
            equity_br += a["value"]
        holdings.append({"ticker": a["ticker"], "value": a["value"], "region": region, "asset_class": a["asset_class"],
                         "region_manual": region_of.get(a["iid"], {}).get("manual", False)})
    equity = equity_br + equity_intl
    investable = fixed + equity
    configured = targets["fixed_pct"] is not None and targets["equity_pct"] is not None
    intl_share = targets["intl_pct"] if targets["intl_pct"] is not None else None

    def bucket(key: str, value: int, target_pct: float | None, base: int) -> dict[str, Any]:
        current_pct = value / base if base else None
        target_value = int(round(base * target_pct)) if target_pct is not None else None
        return {
            "key": key, "label": BUCKETS[key], "value": value, "pct": current_pct, "target_pct": target_pct,
            "target_value": target_value, "gap": target_value - value if target_value is not None else None,
            "drift": current_pct - target_pct if current_pct is not None and target_pct is not None else None,
        }

    equity_br_target = targets["equity_pct"] * (1 - intl_share) if configured and intl_share is not None else None
    equity_intl_target = targets["equity_pct"] * intl_share if configured and intl_share is not None else None
    buckets = [
        bucket("fixed", fixed, targets["fixed_pct"], investable),
        bucket("equity_br", equity_br, equity_br_target if intl_share is not None else targets["equity_pct"], investable),
        bucket("equity_intl", equity_intl, equity_intl_target, investable),
    ]
    if intl_share is None:
        # sem meta internacional, a renda variável é uma classe só
        buckets[1] = {**bucket("equity_br", equity, targets["equity_pct"], investable), "label": "Renda variável"}
        buckets = buckets[:2]
    reserve_info = {
        "key": "reserve", "label": BUCKETS["reserve"], "value": reserve, "target_value": reserve_target,
        "gap": reserve_target - reserve if reserve_target is not None else None,
        "free_cash": free_cash, "cash": cash, "card_debt": card_debt, "excess_cash": excess_cash,
    }
    return {
        "targets": targets, "configured": configured or reserve_target is not None, "reserve": reserve_info,
        "buckets": buckets, "investable": investable, "equity": equity, "fixed_products": fixed_products,
        "pension": pension, "holdings": holdings,
        "equity_intl_share": equity_intl / equity if equity else None,
        "alerts": drift_alerts(reserve_info, buckets),
        "rebalance_without_selling": _needed_to_balance(buckets, investable),
    }


def _needed_to_balance(buckets: list[dict[str, Any]], investable: int) -> int | None:
    """Aporte mínimo para que nenhuma classe fique acima da meta, sem vender nada."""
    ratios = [b["value"] / b["target_pct"] for b in buckets if b["target_pct"]]
    if not ratios or any(b["target_pct"] is None for b in buckets):
        return None
    return max(int(max(ratios) - investable), 0)


def _pp(fraction: float) -> str:
    return f"{fraction * 100:.1f}".replace(".", ",")


def drift_alerts(reserve: dict[str, Any], buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    if reserve["target_value"] is not None and reserve["gap"] and reserve["gap"] > 0:
        alerts.append({"severity": "critico" if reserve["value"] < reserve["target_value"] / 2 else "atencao",
                       "message": f"Reserva de emergência abaixo da meta: faltam {brl(reserve['gap'])}."})
    for b in buckets:
        if b["drift"] is not None and abs(b["drift"]) >= DRIFT_ALERT:
            direction = "acima" if b["drift"] > 0 else "abaixo"
            alerts.append({"severity": "atencao",
                           "message": f"{b['label']} {_pp(abs(b['drift']))} p.p. {direction} da meta "
                                      f"({_pp(b['pct'])}% contra {_pp(b['target_pct'])}%)."})
    return alerts


def contribution_plan(snap: dict[str, Any], amount: int) -> list[dict[str, Any]]:
    """Para onde vai um aporte de `amount` centavos, sem vender nada."""
    plan: list[dict[str, Any]] = []
    remaining = max(amount, 0)
    reserve = snap["reserve"]
    if reserve["target_value"] is not None and reserve["gap"] and reserve["gap"] > 0 and remaining:
        to_reserve = min(reserve["gap"], remaining)
        plan.append({"key": "reserve", "label": reserve["label"], "amount": to_reserve,
                     "reason": "Completar a reserva de emergência vem antes de investir."})
        remaining -= to_reserve
    buckets = [b for b in snap["buckets"] if b["target_pct"] is not None]
    if not remaining or not buckets:
        return plan
    new_base = snap["investable"] + remaining
    deficits = {b["key"]: max(new_base * b["target_pct"] - b["value"], 0) for b in buckets}
    total_deficit = sum(deficits.values())
    shares: dict[str, float] = {}
    if total_deficit >= remaining:
        shares = {k: remaining * d / total_deficit for k, d in deficits.items()}
    else:
        leftover = remaining - total_deficit
        shares = {b["key"]: deficits[b["key"]] + leftover * b["target_pct"] for b in buckets}
    allocated = 0
    ordered = sorted(buckets, key=lambda b: -shares[b["key"]])
    for index, b in enumerate(ordered):
        value = int(round(shares[b["key"]])) if index < len(ordered) - 1 else remaining - allocated
        allocated += value
        if value <= 0:
            continue
        after = (b["value"] + value) / new_base
        plan.append({"key": b["key"], "label": b["label"], "amount": value, "pct_after": after,
                     "reason": f"Está em {_pp(b['pct'])}% para meta de {_pp(b['target_pct'])}%."
                     if b["pct"] is not None else "Classe ainda vazia."})
    return plan


def suggested_amount(flow: list[dict[str, Any]]) -> int:
    """Sugestão de aporte: média do saldo (receitas − despesas) dos últimos 3 meses fechados."""
    closed = flow[-4:-1] if len(flow) >= 4 else flow[:-1]
    positives = [m["net"] for m in closed]
    return max(int(sum(positives) / len(positives)), 0) if positives else 0
