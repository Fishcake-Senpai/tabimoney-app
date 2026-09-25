"""Cálculos da carteira e do patrimônio, feitos em Python sobre o SQLite local.

Convenções: dinheiro em centavos (int), quantidades em milionésimos (int), retornos como fração (float).

Regras de consolidação (evitam contar o mesmo ativo duas vezes quando há várias origens):
- Posições: por (apelido da conta, ativo) vale o snapshot mais recente; movimentações posteriores a ele somam.
- Operações: por (apelido, ativo, grupo) usa uma única origem, pela prioridade B3 > B3 mov. > Open Finance > CSV.
- Renda fixa e saldos: por apelido da conta, usa a origem com o dado mais recente.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.db import rows
from app.services.categories import INCOME_CATEGORIES, INTERNAL_CATEGORIES
from app.services.spending import apply_overrides

TRADE_IN = {"BUY", "TRANSFER_IN"}
TRADE_OUT = {"SELL", "TRANSFER_OUT"}
CORPORATE = {"SPLIT", "BONUS"}
INCOME = {"DIVIDEND", "JCP", "INCOME", "INTEREST"}
SOURCE_PRIORITY = {"b3": 0, "b3_mov": 1, "pluggy": 2, "manual_ops": 3, "manual": 4}
SNAPSHOT_PRIORITY = {"pluggy": 0, "b3": 1, "manual": 2}
QUOTE_PRIORITY = {"manual": 0, "brapi": 1, "b3": 2}
QTY_EPSILON = 100  # 0,0001 unidade
PENSION = "Previdência"


def _group(event_type: str) -> str:
    if event_type in TRADE_IN | TRADE_OUT:
        return "trade"
    if event_type in CORPORATE:
        return "corp"
    if event_type in INCOME:
        return "income"
    return event_type.lower()


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


def _asof(dates: list[str], values: list[Any], day: str) -> Any:
    index = bisect_right(dates, day) - 1
    return values[index] if index >= 0 else None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


@dataclass
class PositionKey:
    account: str
    instrument_id: int
    snap_dates: list[str] = field(default_factory=list)
    snap_qty: list[int] = field(default_factory=list)
    # movimentos de quantidade (sem OPENING) para somar após o snapshot
    move_dates: list[str] = field(default_factory=list)
    move_cum: list[int] = field(default_factory=list)
    corp_cum: list[int] = field(default_factory=list)
    # linha do tempo de operações: (data, qty, custo, custo_conhecido)
    timeline_dates: list[str] = field(default_factory=list)
    timeline: list[tuple[int, int, bool]] = field(default_factory=list)
    realized: int = 0
    realized_known: bool = True
    income: list[tuple[str, int]] = field(default_factory=list)

    def _cum(self, arr: list[int], day: str) -> int:
        index = bisect_right(self.move_dates, day) - 1
        return arr[index] if index >= 0 else 0

    def qty_at(self, day: str) -> int:
        index = bisect_right(self.snap_dates, day) - 1
        if index >= 0:
            base_day = self.snap_dates[index]
            return self.snap_qty[index] + self._cum(self.move_cum, day) - self._cum(self.move_cum, base_day)
        if self.snap_dates:
            # Antes da primeira posição: desfaz as operações entre o dia e a posição.
            first = self.snap_dates[0]
            return max(0, self.snap_qty[0] - (self._cum(self.move_cum, first) - self._cum(self.move_cum, day)))
        state = _asof(self.timeline_dates, self.timeline, day)
        return state[0] if state else 0

    def corp_between(self, start: str, end: str) -> int:
        return self._cum(self.corp_cum, end) - self._cum(self.corp_cum, start)

    def trade_state(self, day: str) -> tuple[int, int, bool] | None:
        return _asof(self.timeline_dates, self.timeline, day)


class Book:
    """Carrega tudo uma vez por requisição e responde às perguntas das telas."""

    def __init__(self) -> None:
        self.today = date.today().isoformat()
        self.instruments = {
            int(r["id"]): {"ticker": r["ticker"], "name": r["name"], "asset_class": r["asset_class"]}
            for r in rows("SELECT id, ticker, name, asset_class FROM instrument")
        }
        self._load_quotes()
        self._load_positions()
        self._load_fixed_income()
        self._load_benchmarks()
        self._load_balances()
        self._series: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------ carga

    def _load_quotes(self) -> None:
        chosen: dict[tuple[int, str], tuple[int, int]] = {}
        for r in rows("SELECT instrument_id, trade_date, close_cents, provider FROM daily_quote"):
            key = (int(r["instrument_id"]), r["trade_date"])
            rank = QUOTE_PRIORITY.get(r["provider"], 9)
            if key not in chosen or rank < chosen[key][0]:
                chosen[key] = (rank, int(r["close_cents"]))
        per: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for (iid, day), (_, close) in chosen.items():
            per[iid].append((day, close))
        self.quote_dates: dict[int, list[str]] = {}
        self.quote_values: dict[int, list[int]] = {}
        for iid, points in per.items():
            points.sort()
            self.quote_dates[iid] = [p[0] for p in points]
            self.quote_values[iid] = [p[1] for p in points]

    def close_at(self, iid: int, day: str, backfill: bool = False) -> int | None:
        dates = self.quote_dates.get(iid)
        if not dates:
            return None
        value = _asof(dates, self.quote_values[iid], day)
        if value is None and backfill:
            return self.quote_values[iid][0]
        return value

    def _load_positions(self) -> None:
        keys: dict[tuple[str, int], PositionKey] = {}

        def key_for(account: str, iid: int) -> PositionKey:
            return keys.setdefault((account, iid), PositionKey(account, iid))

        snaps: dict[tuple[str, int], dict[str, tuple[int, int]]] = defaultdict(dict)
        for r in rows(
            "SELECT a.account_name, ps.instrument_id, ps.as_of_date, ps.quantity_micros, ps.source "
            "FROM position_snapshot ps JOIN financial_account a ON a.id = ps.account_id"
        ):
            k = (r["account_name"], int(r["instrument_id"]))
            rank = SNAPSHOT_PRIORITY.get(r["source"], 9)
            current = snaps[k].get(r["as_of_date"])
            if current is None or rank < current[0]:
                snaps[k][r["as_of_date"]] = (rank, int(r["quantity_micros"]))
        for k, by_day in snaps.items():
            pk = key_for(*k)
            for day in sorted(by_day):
                pk.snap_dates.append(day)
                pk.snap_qty.append(by_day[day][1])

        events = rows(
            "SELECT a.account_name, e.instrument_id, e.event_date, e.event_type, e.quantity_micros, "
            "e.amount_cents, e.source, e.id FROM investment_event e JOIN financial_account a ON a.id = e.account_id "
            "ORDER BY e.event_date, e.id"
        )
        best_source: dict[tuple[str, int, str], int] = {}
        for e in events:
            group_key = (e["account_name"], int(e["instrument_id"]), _group(e["event_type"]))
            rank = SOURCE_PRIORITY.get(e["source"], 9)
            best_source[group_key] = min(best_source.get(group_key, 99), rank)
        chosen_events: dict[tuple[str, int], list[Any]] = defaultdict(list)
        for e in events:
            group = _group(e["event_type"])
            k = (e["account_name"], int(e["instrument_id"]))
            if group != "opening" and SOURCE_PRIORITY.get(e["source"], 9) != best_source[(k[0], k[1], group)]:
                continue
            chosen_events[k].append(e)

        for k, evs in chosen_events.items():
            pk = key_for(*k)
            openings = [e for e in evs if e["event_type"] == "OPENING"]
            opening_day = openings[-1]["event_date"] if openings else None
            qty = cost = 0
            cost_ok = True
            move_total = corp_total = 0
            for e in evs:
                kind = e["event_type"]
                q = int(e["quantity_micros"] or 0)
                amount = e["amount_cents"]
                day = e["event_date"]
                if kind in INCOME:
                    if amount:
                        pk.income.append((day, abs(int(amount))))
                    continue
                if opening_day and day <= opening_day and kind != "OPENING":
                    continue
                if kind == "OPENING":
                    if e is not openings[-1]:
                        continue
                    qty, cost, cost_ok = q, int(amount or 0), amount is not None
                elif kind in TRADE_IN:
                    qty += abs(q)
                    if amount is None:
                        cost_ok = False
                    else:
                        cost += abs(int(amount))
                    move_total += abs(q)
                elif kind in TRADE_OUT:
                    sold = abs(q)
                    average = cost / qty if qty > 0 else 0
                    if kind == "SELL":
                        if amount is None or not cost_ok:
                            pk.realized_known = False
                        else:
                            pk.realized += int(round(abs(int(amount)) - average * sold))
                    cost -= int(round(average * min(sold, qty)))
                    qty -= sold
                    move_total -= sold
                elif kind in CORPORATE:
                    qty += q
                    move_total += q
                    corp_total += q
                else:
                    continue
                if kind != "OPENING":
                    pk.move_dates.append(day)
                    pk.move_cum.append(move_total)
                    pk.corp_cum.append(corp_total)
                if pk.timeline_dates and pk.timeline_dates[-1] == day:
                    pk.timeline[-1] = (qty, max(cost, 0), cost_ok)
                else:
                    pk.timeline_dates.append(day)
                    pk.timeline.append((qty, max(cost, 0), cost_ok))
            # move_* precisa de uma entrada por data: mantém a última de cada dia
            dedup: dict[str, tuple[int, int]] = {}
            for day, move, corp in zip(pk.move_dates, pk.move_cum, pk.corp_cum):
                dedup[day] = (move, corp)
            pk.move_dates = sorted(dedup)
            pk.move_cum = [dedup[d][0] for d in pk.move_dates]
            pk.corp_cum = [dedup[d][1] for d in pk.move_dates]

        self.position_keys = list(keys.values())
        self.by_instrument: dict[int, list[PositionKey]] = defaultdict(list)
        for pk in self.position_keys:
            self.by_instrument[pk.instrument_id].append(pk)

    def qty_at(self, iid: int, day: str) -> int:
        return sum(pk.qty_at(day) for pk in self.by_instrument.get(iid, []))

    def _load_fixed_income(self) -> None:
        data = rows(
            "SELECT f.*, a.account_name FROM fixed_income_snapshot f JOIN financial_account a ON a.id = f.account_id "
            "ORDER BY f.as_of_date"
        )
        # Por apelido: entre Open Finance e B3 (fotografias completas) vale a mais recente; o CSV manual
        # (caixinhas) soma à B3, que não as enxerga, mas sai quando o Open Finance existe, pois ele já as traz.
        latest_by_source: dict[tuple[str, str], str] = {}
        for r in data:
            k = (r["account_name"], r["source"])
            latest_by_source[k] = max(latest_by_source.get(k, ""), r["as_of_date"])
        allowed: dict[str, set[str]] = defaultdict(set)
        for account in {account for account, _ in latest_by_source}:
            automated = [s for s in ("pluggy", "b3") if (account, s) in latest_by_source]
            if automated:
                allowed[account].add(max(automated, key=lambda s: latest_by_source[(account, s)]))
            if "pluggy" not in automated and (account, "manual") in latest_by_source:
                allowed[account].add("manual")
        self.fi_products: dict[str, dict[str, Any]] = {}
        for r in data:
            if r["source"] not in allowed.get(r["account_name"], set()):
                continue
            product = self.fi_products.setdefault(
                r["product_key"], {"dates": [], "values": [], "rows": [], "purchase": None, "invested": None}
            )
            product["dates"].append(r["as_of_date"])
            product["values"].append(int(r["gross_value_cents"]))
            product["rows"].append(dict(r))
            product["purchase"] = product["purchase"] or r["purchase_date"]
            if product["invested"] is None and r["invested_cents"]:
                product["invested"] = int(r["invested_cents"])

    @staticmethod
    def _product_value_at(product: dict[str, Any], day: str) -> int:
        value = _asof(product["dates"], product["values"], day)
        if value is not None:
            index = bisect_right(product["dates"], day)
            if product["rows"][-1]["product_type"] == PENSION and 0 < index < len(product["dates"]):
                # Previdência recebe aporte todo mês, mas o extrato é lançado de vez em quando: linha reta entre extratos.
                start, end = product["dates"][index - 1], product["dates"][index]
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days
                elapsed = (date.fromisoformat(day) - date.fromisoformat(start)).days
                return value + (product["values"][index] - value) * elapsed // span
            return value
        # Antes da primeira fotografia: zero antes da aplicação; depois, do valor aplicado ao da fotografia em linha reta.
        purchase, invested = product["purchase"], product["invested"]
        if not purchase or invested is None or day < purchase:
            return 0
        first_day, first_value = product["dates"][0], product["values"][0]
        span = (date.fromisoformat(first_day) - date.fromisoformat(purchase)).days
        if span <= 0:
            return first_value
        elapsed = (date.fromisoformat(day) - date.fromisoformat(purchase)).days
        return invested + (first_value - invested) * elapsed // span

    def fixed_income_at(self, day: str) -> int:
        return sum(
            self._product_value_at(p, day) for p in self.fi_products.values() if p["rows"][-1]["product_type"] != PENSION
        )

    def pension_at(self, day: str) -> int:
        return sum(
            self._product_value_at(p, day) for p in self.fi_products.values() if p["rows"][-1]["product_type"] == PENSION
        )

    def _load_balances(self) -> None:
        data = rows(
            "SELECT s.account_id, s.as_of_date, s.balance_cents, s.source, a.account_name, a.account_type, a.provider, "
            "a.credit_limit_cents, a.available_limit_cents, a.institution "
            "FROM account_balance_snapshot s JOIN financial_account a ON a.id = s.account_id "
            "WHERE a.account_type IN ('BANK', 'CREDIT') ORDER BY s.as_of_date, s.imported_at"
        )
        latest_by_account: dict[int, str] = {}
        info: dict[int, Any] = {}
        for r in data:
            latest_by_account[int(r["account_id"])] = r["as_of_date"]
            info[int(r["account_id"])] = r
        winner: dict[tuple[str, str], int] = {}
        for account_id, day in latest_by_account.items():
            r = info[account_id]
            k = (r["account_name"], r["account_type"])
            current = winner.get(k)
            if current is None or (day, r["provider"] == "pluggy") > (latest_by_account[current], info[current]["provider"] == "pluggy"):
                winner[k] = account_id
        movements: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for t in cash_transactions():
            movements[t["account_name"]][t["transaction_date"]] += int(t["amount_cents"])
        self.movements = movements
        yield_settings = cdi_yield_settings()
        self.balance_series: dict[str, dict[str, Any]] = {}
        self.history_start: str | None = None
        for (name, kind), account_id in winner.items():
            by_day: dict[str, int] = {}
            for r in data:
                if int(r["account_id"]) == account_id:
                    by_day[r["as_of_date"]] = int(r["balance_cents"])
            days = sorted(by_day)
            meta = info[account_id]
            move_days = sorted(movements.get(name, {}))
            running = 0
            move_cum = []
            for d in move_days:
                running += movements[name][d]
                move_cum.append(running)
            self.balance_series[name] = {
                "type": kind, "dates": days, "values": [by_day[d] for d in days], "source": meta["source"],
                "limit": meta["credit_limit_cents"], "available": meta["available_limit_cents"],
                "move_dates": move_days, "move_cum": move_cum, "institution": meta["institution"],
                "cdi_pct": cdi_yield_pct(yield_settings, name, kind, meta["institution"]), "back": {},
            }
            # O histórico reconstruído só vale a partir da primeira movimentação de cada conta.
            if move_days and move_days[0] < days[0]:
                self.history_start = max(self.history_start or move_days[0], move_days[0])
        for name, series in self.balance_series.items():
            if series["type"] == "BANK" and series["cdi_pct"] > 0:
                self._rebuild_with_yield(name, series)
        self._compute_yields()

    def _daily_rate(self, day: str, pct: float) -> float:
        return self.cdi.get(day, 0.0) / 100 * pct / 100

    def _rebuild_with_yield(self, name: str, series: dict[str, Any]) -> None:
        """Antes do primeiro saldo, desfaz dia a dia a movimentação e o rendimento do CDI.

        saldo(d) = saldo(d−1) × (1 + taxa(d)) + movimentação(d)  ⇒  saldo(d−1) = (saldo(d) − movimentação(d)) / (1 + taxa(d)).
        O Nubank não lança o rendimento no extrato; sem isso, o juro do ano seria atribuído ao passado.
        """
        first = series["dates"][0]
        start = series["move_dates"][0] if series["move_dates"] else first
        if start >= first:
            return
        day = date.fromisoformat(first)
        stop = date.fromisoformat(start) - timedelta(days=1)
        balance = float(series["values"][0])
        moves = self.movements.get(name, {})
        while day > stop:
            iso = day.isoformat()
            balance = (balance - moves.get(iso, 0)) / (1 + self._daily_rate(iso, series["cdi_pct"]))
            day -= timedelta(days=1)
            series["back"][day.isoformat()] = int(round(balance))

    def _compute_yields(self) -> None:
        """Rendimento diário do CDI por conta: estimado pelo saldo do dia anterior e, onde houver dois saldos
        reais, calibrado para bater com o medido (saldo final − saldo inicial − movimentações)."""
        self.yield_days: dict[str, list[dict[str, Any]]] = {}
        self.yield_checks: list[dict[str, Any]] = []
        for name, series in self.balance_series.items():
            if series["type"] != "BANK" or series["cdi_pct"] <= 0:
                continue
            start = min(series["back"] or series["dates"])
            days = [d for d in self.cdi_dates if start < d <= self.today]
            entries = []
            for day in days:
                previous = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                balance = max(self._balance_at(series, previous), 0)
                entries.append({"d": day, "est": balance * self._daily_rate(day, series["cdi_pct"]),
                                "balance": balance, "rate": self.cdi[day], "measured": False})
            # dias úteis sem CDI publicado ainda (hoje, antes da divulgação): repete a última taxa
            last_rate_day = self.cdi_dates[-1] if self.cdi_dates else None
            if last_rate_day:
                cursor = date.fromisoformat(last_rate_day) + timedelta(days=1)
                while cursor.isoformat() <= self.today:
                    if cursor.weekday() < 5:
                        iso = cursor.isoformat()
                        previous = (cursor - timedelta(days=1)).isoformat()
                        balance = max(self._balance_at(series, previous), 0)
                        rate = self.cdi[last_rate_day] / 100 * series["cdi_pct"] / 100
                        entries.append({"d": iso, "est": balance * rate, "balance": balance,
                                        "rate": self.cdi[last_rate_day], "measured": False, "provisional": True})
                    cursor += timedelta(days=1)
            moves = self.movements.get(name, {})
            for (d0, v0), (d1, v1) in zip(zip(series["dates"], series["values"]), list(zip(series["dates"], series["values"]))[1:]):
                window = [e for e in entries if d0 < e["d"] <= d1]
                estimated = sum(e["est"] for e in window)
                moved = sum(amount for day, amount in moves.items() if d0 < day <= d1)
                measured = v1 - v0 - moved
                reliable = estimated > 0 and 0 <= measured <= 3 * estimated + 100
                self.yield_checks.append({"account": name, "start": d0, "end": d1, "estimated": int(round(estimated)),
                                          "measured": measured, "reliable": reliable})
                if reliable:
                    factor = measured / estimated
                    for e in window:
                        e["est"] *= factor
                        e["measured"] = True
            self.yield_days[name] = entries

    def yield_by_month(self) -> list[dict[str, Any]]:
        months: dict[tuple[str, str], dict[str, Any]] = {}
        for name, entries in self.yield_days.items():
            for e in entries:
                key = (e["d"][:7], name)
                m = months.setdefault(key, {"m": key[0], "account": name, "cents": 0.0, "days": 0, "measured_days": 0,
                                            "balance_sum": 0, "growth": 1.0})
                m["cents"] += e["est"]
                m["days"] += 1
                m["measured_days"] += 1 if e["measured"] else 0
                m["balance_sum"] += e["balance"]
                m["growth"] *= 1 + e["rate"] / 100
        output = []
        for (month, name), m in sorted(months.items()):
            output.append({
                "m": month, "account": name, "cents": int(round(m["cents"])),
                "avg_balance": m["balance_sum"] // m["days"] if m["days"] else 0,
                "cdi": m["growth"] - 1, "pct": self.balance_series[name]["cdi_pct"],
                "measured": m["measured_days"] == m["days"], "partial_measured": 0 < m["measured_days"] < m["days"],
            })
        return output

    def yield_entries(self) -> list[dict[str, Any]]:
        """Rendimento do CDI como lançamentos mensais de receita (um por conta e mês), para o fluxo de caixa."""
        output = []
        for row in self.yield_by_month():
            if row["cents"] <= 0:
                continue
            last_day = (date.fromisoformat(row["m"] + "-01") + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            output.append({
                "id": 0, "transaction_date": min(last_day.isoformat(), self.today),
                "description": f"Rendimento {row['pct']:g}% do CDI" + ("" if row["measured"] else " (estimado)"),
                "amount_cents": row["cents"], "status": "POSTED", "category": YIELD_CATEGORY, "source": "cdi",
                "account_name": row["account"], "account_type": "BANK", "provider": "cdi", "institution": None,
                "synthetic": True,
            })
        return output

    @staticmethod
    def _balance_at(s: dict[str, Any], day: str) -> int:
        value = _asof(s["dates"], s["values"], day)
        if value is not None:
            return value
        if day in s.get("back", {}):
            return s["back"][day]
        # Antes do primeiro saldo conhecido: saldo = primeiro saldo − movimentações entre o dia e ele.
        first = s["dates"][0]
        until_first = _asof(s["move_dates"], s["move_cum"], first) or 0
        until_day = _asof(s["move_dates"], s["move_cum"], day) or 0
        return s["values"][0] - (until_first - until_day)

    def cash_at(self, day: str) -> int:
        return sum(self._balance_at(s, day) for s in self.balance_series.values() if s["type"] == "BANK")

    def card_debt_at(self, day: str) -> int:
        """Fatura em aberto, negativa: entra no patrimônio como dívida."""
        return sum(self._balance_at(s, day) for s in self.balance_series.values() if s["type"] == "CREDIT")

    def _load_benchmarks(self) -> None:
        self.cdi: dict[str, float] = {}
        self.ibov_dates: list[str] = []
        self.ibov_values: list[float] = []
        for r in rows("SELECT code, trade_date, value FROM benchmark_quote ORDER BY trade_date"):
            if r["code"] == "CDI":
                self.cdi[r["trade_date"]] = float(r["value"])
            elif r["code"] == "IBOV":
                self.ibov_dates.append(r["trade_date"])
                self.ibov_values.append(float(r["value"]))
        self.cdi_dates = sorted(self.cdi)

    # ------------------------------------------------------------ série diária

    def series(self) -> list[dict[str, Any]]:
        """Patrimônio dia a dia e retorno diário da renda variável (método de cotas/TWR)."""
        if self._series is not None:
            return self._series
        held = [iid for iid in self.by_instrument if iid in self.quote_dates]
        day_set: set[str] = set()
        for iid in held:
            day_set.update(self.quote_dates[iid])
        for pk in self.position_keys:
            day_set.update(pk.snap_dates)
            day_set.update(pk.timeline_dates)
        for product in self.fi_products.values():
            day_set.update(product["dates"])
        for s in self.balance_series.values():
            day_set.update(s["dates"])
        days = sorted(d for d in day_set if d <= self.today and (not self.history_start or d >= self.history_start))
        income_by_day: dict[str, int] = defaultdict(int)
        for pk in self.position_keys:
            for day, amount in pk.income:
                income_by_day[day] += amount
        income_days = sorted(income_by_day)
        income_cum = []
        running = 0
        for d in income_days:
            running += income_by_day[d]
            income_cum.append(running)

        output: list[dict[str, Any]] = []
        previous_day: str | None = None
        previous_equity = 0
        capital = 0
        previous_qty: dict[int, int] = {}
        started = False
        for day in days:
            equity = 0
            flow = 0
            for iid in held:
                qty = self.qty_at(iid, day)
                if qty == 0 and previous_qty.get(iid, 0) == 0:
                    continue
                close = self.close_at(iid, day, backfill=True) or 0
                equity += qty * close // 1_000_000
                corp = sum(pk.corp_between(previous_day, day) for pk in self.by_instrument[iid]) if previous_day else 0
                delta = qty - previous_qty.get(iid, 0) - corp
                flow += delta * close // 1_000_000
                previous_qty[iid] = qty
            fixed = self.fixed_income_at(day)
            pension = self.pension_at(day)
            cash = self.cash_at(day)
            debt = self.card_debt_at(day)
            if not started and equity == 0 and fixed == 0 and pension == 0 and cash == 0:
                previous_day = day
                continue
            if not started:
                capital = equity
                started = True
            else:
                capital += flow
            income = 0
            if previous_day:
                income = (_asof(income_days, income_cum, day) or 0) - (_asof(income_days, income_cum, previous_day) or 0)
            daily_return = 0.0
            if previous_equity > 0:
                daily_return = (equity - flow + income) / previous_equity - 1
                if abs(daily_return) > 0.5:  # dado faltante/split não registrado: não contamina a série
                    daily_return = 0.0
            output.append({
                "d": day, "eq": equity, "fi": fixed, "pv": pension, "cash": cash, "debt": debt,
                "nw": equity + fixed + pension + cash + debt,
                "cap": capital, "r": round(daily_return, 8),
            })
            previous_equity = equity
            previous_day = day
        self._series = output
        return output

    # ------------------------------------------------------------ retornos

    def twr(self, start: str, end: str | None = None) -> float | None:
        series = [p for p in self.series() if p["d"] > start and (end is None or p["d"] <= end)]
        if not series or all(p["eq"] == 0 for p in series):
            return None
        total = 1.0
        for p in series:
            total *= 1 + p["r"]
        return total - 1

    def cdi_return(self, start: str, end: str | None = None) -> float | None:
        end = end or self.today
        lo, hi = bisect_right(self.cdi_dates, start), bisect_right(self.cdi_dates, end)
        if hi <= lo:
            return None
        total = 1.0
        for day in self.cdi_dates[lo:hi]:
            total *= 1 + self.cdi[day] / 100
        return total - 1

    def ibov_return(self, start: str, end: str | None = None) -> float | None:
        base = _asof(self.ibov_dates, self.ibov_values, start)
        last = _asof(self.ibov_dates, self.ibov_values, end or self.today)
        return last / base - 1 if base and last else None

    def windows(self) -> dict[str, str]:
        last = self.series()[-1]["d"] if self.series() else self.today
        first = self.series()[0]["d"] if self.series() else self.today
        year_start = (date.fromisoformat(last).replace(month=1, day=1) - timedelta(days=1)).isoformat()
        return {
            "1M": _shift(last, 30), "3M": _shift(last, 91), "6M": _shift(last, 182),
            "YTD": year_start, "12M": _shift(last, 365), "Início": _shift(first, 1),
        }

    def risk(self) -> dict[str, float | None]:
        series = self.series()
        start = _shift(series[-1]["d"], 365) if series else self.today
        returns = [p["r"] for p in series if p["d"] > start and p["eq"] > 0]
        volatility = None
        if len(returns) > 20:
            mean = sum(returns) / len(returns)
            volatility = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) * math.sqrt(252)
        peak = index = 1.0
        drawdown = 0.0
        for p in series:
            if p["eq"] <= 0:
                continue
            index *= 1 + p["r"]
            peak = max(peak, index)
            drawdown = min(drawdown, index / peak - 1)
        return {"volatility": volatility, "max_drawdown": drawdown if series else None}

    def monthly_returns(self, months: int = 12) -> list[dict[str, Any]]:
        by_month: dict[str, float] = {}
        for p in self.series():
            if p["eq"] <= 0 and p["r"] == 0:
                continue
            month = p["d"][:7]
            by_month[month] = (1 + by_month.get(month, 0.0)) * (1 + p["r"]) - 1
        cdi_month: dict[str, float] = {}
        for day in self.cdi_dates:
            month = day[:7]
            cdi_month[month] = (1 + cdi_month.get(month, 0.0)) * (1 + self.cdi[day] / 100) - 1
        return [
            {"m": month, "r": round(value, 6), "cdi": round(cdi_month[month], 6) if month in cdi_month else None}
            for month, value in sorted(by_month.items())[-months:]
        ]

    # ------------------------------------------------------------ ativos

    def assets(self) -> list[dict[str, Any]]:
        last_day = self.today
        output = []
        for iid, keys in self.by_instrument.items():
            qty = self.qty_at(iid, last_day)
            meta = self.instruments[iid]
            income_all = sum(a for pk in keys for _, a in pk.income)
            income_12m = sum(a for pk in keys for d, a in pk.income if d > _shift(last_day, 365))
            realized = sum(pk.realized for pk in keys)
            if qty <= QTY_EPSILON and not income_all and not realized:
                continue
            dates = self.quote_dates.get(iid, [])
            values = self.quote_values.get(iid, [])
            close = values[-1] if values else None
            previous = values[-2] if len(values) > 1 else None
            quote_day = dates[-1] if dates else None
            value = qty * close // 1_000_000 if close is not None else None
            # custo: soma do custo de cada conta; se a quantidade operada difere da custodiada, estima pelo PM
            cost = 0
            cost_status = "ok"
            traded_qty = 0
            for pk in keys:
                state = pk.trade_state(last_day)
                held = pk.qty_at(last_day)
                if held <= QTY_EPSILON:
                    continue
                if not state or state[0] <= 0 or not state[2]:
                    cost_status = "missing"
                    continue
                traded_qty += state[0]
                average = state[1] / state[0]
                cost += int(round(average * held))
                if abs(state[0] - held) > QTY_EPSILON:
                    cost_status = "estimated" if cost_status == "ok" else cost_status
            if qty <= QTY_EPSILON:
                cost_status = "closed"
            has_cost = cost_status in {"ok", "estimated"} and cost > 0
            average_price = cost * 1_000_000 // qty if has_cost and qty else None
            unrealized = value - cost if has_cost and value is not None else None

            def price_return(days: int) -> float | None:
                if close is None:
                    return None
                base = _asof(dates, values, _shift(quote_day, days))
                return close / base - 1 if base else None

            year_window = [v for d, v in zip(dates, values) if quote_day and d > _shift(quote_day, 365)]
            high = max(year_window) if year_window else None
            low = min(year_window) if year_window else None
            output.append({
                "iid": iid, "ticker": meta["ticker"], "name": meta["name"], "asset_class": meta["asset_class"],
                "qty": qty, "close": close, "quote_date": quote_day,
                "quote_status": "missing" if close is None else "stale" if quote_day < _shift(last_day, 4) else "ok",
                "day_pct": close / previous - 1 if close and previous else None,
                "day_cents": qty * (close - previous) // 1_000_000 if close and previous else None,
                "value": value, "cost": cost if has_cost else None, "average_price": average_price,
                "cost_status": cost_status, "unrealized": unrealized,
                "unrealized_pct": _pct(unrealized, cost) if has_cost else None,
                "realized": realized, "income": income_all, "income_12m": income_12m,
                "yoc": _pct(income_12m, cost) if has_cost else None,
                "dy": _pct(income_12m, value) if value else None,
                "r1m": price_return(30), "r3m": price_return(91), "r12m": price_return(365),
                "high52": high, "low52": low,
                "from_high": close / high - 1 if close and high else None,
            })
        total = sum(a["value"] or 0 for a in output)
        for a in output:
            a["weight"] = _pct(a["value"], total) if a["value"] else None
        output.sort(key=lambda a: (-(a["value"] or 0), a["ticker"]))
        return output

    def portfolio_kpis(self, assets: list[dict[str, Any]]) -> dict[str, Any]:
        open_assets = [a for a in assets if a["qty"] > QTY_EPSILON]
        value = sum(a["value"] or 0 for a in open_assets)
        costed = [a for a in open_assets if a["cost"] is not None and a["value"] is not None]
        cost = sum(a["cost"] for a in costed)
        unrealized = sum(a["unrealized"] for a in costed)
        day = [a for a in open_assets if a["day_cents"] is not None]
        day_cents = sum(a["day_cents"] for a in day)
        income_12m = sum(a["income_12m"] for a in assets)
        weights = sorted((a["weight"] or 0 for a in open_assets), reverse=True)
        windows = self.windows()
        returns = {
            label: {"twr": self.twr(start), "cdi": self.cdi_return(start), "ibov": self.ibov_return(start)}
            for label, start in windows.items()
        }
        return {
            "value": value, "cost": cost if costed else None,
            "cost_coverage": len(costed), "count": len(open_assets),
            "unrealized": unrealized if costed else None,
            "unrealized_pct": _pct(unrealized, cost) if costed else None,
            "realized": sum(a["realized"] for a in assets),
            "day_cents": day_cents if day else None,
            "day_pct": _pct(day_cents, value - day_cents) if day else None,
            "income_12m": income_12m, "income_total": sum(a["income"] for a in assets),
            "dy_12m": _pct(income_12m, value),
            "top5": sum(weights[:5]) if weights else None,
            "missing_quotes": sum(1 for a in open_assets if a["quote_status"] == "missing"),
            "stale_quotes": sum(1 for a in open_assets if a["quote_status"] == "stale"),
            "returns": returns, **self.risk(),
        }

    def allocation(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, int] = defaultdict(int)
        for a in assets:
            if a["value"]:
                buckets[a["asset_class"]] += a["value"]
        for p in self.fixed_income(include_pension=True):
            label = p["product_type"] if p["product_type"] in {"Caixinha", "Tesouro", PENSION, "Fundo"} else "Renda fixa"
            buckets[label] += p["gross"]
        cash = self.cash_at(self.today)
        if cash > 0:
            buckets["Caixa"] += cash
        total = sum(buckets.values())
        return [
            {"label": label, "value": value, "pct": value / total}
            for label, value in sorted(buckets.items(), key=lambda item: -item[1]) if total and value > 0
        ]

    def asset_history(self, iid: int) -> dict[str, Any]:
        events = rows(
            "SELECT e.event_date, e.event_type, e.quantity_micros, e.amount_cents, e.source, a.account_name "
            "FROM investment_event e JOIN financial_account a ON a.id = e.account_id "
            "WHERE e.instrument_id = ? ORDER BY e.event_date DESC, e.id DESC LIMIT 300", (iid,),
        )
        prices = [
            {"d": d, "v": v} for d, v in zip(self.quote_dates.get(iid, []), self.quote_values.get(iid, []))
        ]
        return {"events": [dict(e) for e in events], "prices": prices}

    # ------------------------------------------------------------ renda fixa, contas

    def fixed_income(self, include_pension: bool = False, only_pension: bool = False) -> list[dict[str, Any]]:
        output = []
        for product in self.fi_products.values():
            latest = product["rows"][-1]
            gross = int(latest["gross_value_cents"])
            is_pension = latest["product_type"] == PENSION
            if gross <= 0 or (is_pension and not (include_pension or only_pension)) or (only_pension and not is_pension):
                continue
            invested = latest["invested_cents"]
            maturity = latest["maturity_date"]
            output.append({
                "name": latest["name"], "product_type": latest["product_type"], "issuer": latest["issuer"],
                "indexer": latest["indexer"], "rate": latest["rate"], "maturity": maturity,
                "days_to_maturity": (date.fromisoformat(maturity) - date.today()).days if maturity else None,
                "as_of": latest["as_of_date"], "gross": gross, "net": latest["net_value_cents"],
                "invested": invested, "gain": gross - invested if invested else None,
                "gain_pct": _pct(gross - invested, invested) if invested else None,
                "account": latest["account_name"], "source": latest["source"], "product_key": latest["product_key"],
                "purchase": product["purchase"],
            })
        output.sort(key=lambda p: -p["gross"])
        return output

    def pension(self) -> dict[str, Any]:
        """Previdência: saldo, contribuições e rentabilidade entre extratos, comparada ao CDI.

        Entre dois extratos, o rendimento é a variação do saldo menos o que foi contribuído no intervalo
        (retorno = rendimento / saldo inicial); os intervalos se encadeiam como cotas.
        """
        plans = self.fixed_income(only_pension=True)
        products = [p for p in self.fi_products.values() if p["rows"][-1]["product_type"] == PENSION]
        days = sorted({d for p in products for d in p["dates"]})
        history = []
        for day in days:
            value = contributed = 0
            complete = True
            for product in products:
                row = _asof(product["dates"], product["rows"], day)
                if row is None:
                    continue
                value += int(row["gross_value_cents"])
                if row["invested_cents"] is None:
                    complete = False
                else:
                    contributed += int(row["invested_cents"])
            history.append({"d": day, "eq": value, "cap": contributed if complete else None})
        growth = 1.0
        measured = False
        for previous, current in zip(history, history[1:]):
            if previous["eq"] <= 0 or previous["cap"] is None or current["cap"] is None:
                continue
            gain = current["eq"] - previous["eq"] - (current["cap"] - previous["cap"])
            growth *= 1 + gain / previous["eq"]
            measured = True
        first, last = (history[0], history[-1]) if history else (None, None)
        total = sum(p["gross"] for p in plans)
        known = [p for p in plans if p["invested"] is not None]
        contributed = sum(p["invested"] for p in known)
        gain = sum(p["gross"] for p in known) - contributed
        return {
            "plans": plans, "history": history, "total": total,
            "net": sum(p["net"] or p["gross"] for p in plans),
            "contributed": contributed if known else None,
            "gain": gain if known else None, "gain_pct": _pct(gain, contributed) if known else None,
            "period_return": growth - 1 if measured else None,
            "period_cdi": self.cdi_return(first["d"], last["d"]) if measured else None,
            "period_start": first["d"] if first else None,
            "as_of": max((p["as_of"] for p in plans), default=None),
        }

    def accounts(self) -> list[dict[str, Any]]:
        output = []
        for name, s in self.balance_series.items():
            output.append({
                "name": name, "type": s["type"], "balance": s["values"][-1], "as_of": s["dates"][-1],
                "source": s["source"], "limit": s["limit"], "available": s["available"],
            })
        output.sort(key=lambda a: (a["type"], a["name"]))
        return output


# ---------------------------------------------------------------- movimentações

MATCH_WINDOW_DAYS = 3
TRANSFER_WINDOW_DAYS = 3
BILL_WINDOW_DAYS = 5


def cash_transactions(limit: int | None = None) -> list[dict[str, Any]]:
    """Movimentações de conta e cartão sem contar duas vezes o que veio de duas origens.

    A mesma conta pode chegar por arquivo (OFX/CSV) e por Open Finance, com ids diferentes. Por conta,
    o Open Finance é a origem principal; cada lançamento de arquivo é descartado se casar com um
    lançamento principal ainda livre de mesmo valor em até 3 dias. O casamento é 1 a 1, então duas
    compras iguais legítimas continuam sendo duas. Depois, as transferências entre contas próprias são
    conciliadas (ver match_transfers).
    """
    data = [
        dict(r) for r in rows(
            "SELECT t.id, t.transaction_date, t.description, t.amount_cents, t.status, t.category, t.user_category, "
            "t.source, t.original_currency, t.original_amount_cents, a.account_name, a.account_type, a.provider, a.institution "
            "FROM cash_transaction t JOIN financial_account a ON a.id = t.account_id "
            "WHERE a.account_type IN ('BANK', 'CREDIT') AND (t.status <> 'PENDING' OR "
            "(a.account_type = 'CREDIT' AND t.transaction_date <= date('now', 'localtime'))) "
            "ORDER BY t.transaction_date DESC, t.id DESC"
        )
    ]
    by_account: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in data:
        by_account[r["account_name"]][r["provider"]].append(r)
    dropped: set[int] = set()
    for providers in by_account.values():
        if len(providers) < 2:
            continue
        primary = "pluggy" if "pluggy" in providers else max(providers, key=lambda p: len(providers[p]))
        free: dict[int, list[date]] = defaultdict(list)
        for r in providers[primary]:
            free[int(r["amount_cents"])].append(date.fromisoformat(r["transaction_date"]))
        for provider, items in providers.items():
            if provider == primary:
                continue
            for r in items:
                candidates = free.get(int(r["amount_cents"]))
                if not candidates:
                    continue
                day = date.fromisoformat(r["transaction_date"])
                best = min(range(len(candidates)), key=lambda i: abs((candidates[i] - day).days))
                if abs((candidates[best] - day).days) <= MATCH_WINDOW_DAYS:
                    candidates.pop(best)
                    dropped.add(int(r["id"]))
    output = [r for r in data if int(r["id"]) not in dropped]
    apply_overrides(output)
    match_transfers(output)
    return output[:limit] if limit else output


def match_transfers(transactions: list[dict[str, Any]]) -> int:
    """Concilia o dinheiro que sai de uma conta própria e entra em outra (ex.: salário no Itaú → Nubank).

    Uma saída de conta casa 1 a 1 com uma entrada de mesmo valor em outra conta:
    - conta → conta em até 3 dias, se algum dos lados já é transferência própria (CPF igual ou rótulo da origem);
    - conta → cartão em até 5 dias, se algum dos lados já é pagamento de fatura.
    Os dois lados passam a ser internos (não são receita nem despesa) e ganham `transfer_with`, a conta do outro lado.
    Sem par, a transferência própria continua interna: veio de uma conta que não está conectada.
    """
    incoming: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for t in transactions:
        if t["amount_cents"] > 0:
            incoming[int(t["amount_cents"])].append(t)
    outgoing = sorted(
        (t for t in transactions if t["amount_cents"] < 0 and t["account_type"] == "BANK"),
        key=lambda t: (t["transaction_date"], t["id"]),
    )
    matched = 0
    for out in outgoing:
        out_day = date.fromisoformat(out["transaction_date"])
        best: tuple[int, dict[str, Any], str] | None = None
        if out.get("category_source") == "manual":
            continue
        for candidate in incoming.get(-int(out["amount_cents"]), []):
            if (candidate.get("transfer_with") or candidate["account_name"] == out["account_name"]
                    or candidate.get("category_source") == "manual"):
                continue
            gap = (date.fromisoformat(candidate["transaction_date"]) - out_day).days
            categories = {out["category"], candidate["category"]}
            if candidate["account_type"] == "BANK":
                kind, window = "Transferência própria", TRANSFER_WINDOW_DAYS
            else:
                kind, window = "Pagamento de fatura", BILL_WINDOW_DAYS
            if kind not in categories or not -1 <= gap <= window:
                continue
            if best is None or abs(gap) < best[0]:
                best = (abs(gap), candidate, kind)
        if best is None:
            continue
        _, candidate, kind = best
        for side, other in ((out, candidate), (candidate, out)):
            side["category"] = kind
            side["transfer_with"] = other["account_name"]
        matched += 1
    return matched


def unmatched_transfers(transactions: list[dict[str, Any]], since: str) -> list[dict[str, Any]]:
    """Transferências próprias sem o outro lado: o dinheiro foi ou veio de uma conta não conectada."""
    return [
        t for t in transactions
        if t["category"] == "Transferência própria" and not t.get("transfer_with") and t["transaction_date"] >= since
    ]


def _flow_kind(t: dict[str, Any]) -> str | None:
    """'in' (receita), 'out' (despesa), 'refund' (estorno, abate a despesa) ou None (movimento interno)."""
    category = t["category"] or "Outros"
    if category in INTERNAL_CATEGORIES:
        return None
    if t["amount_cents"] < 0:
        return "out"
    if t["account_type"] == "BANK" and category in INCOME_CATEGORIES:
        return "in"
    return "refund"


def cash_flow(transactions: list[dict[str, Any]], months: int = 12) -> list[dict[str, Any]]:
    by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0})
    for t in transactions:
        kind = _flow_kind(t)
        if kind is None:
            continue
        month = t["transaction_date"][:7]
        amount = int(t["amount_cents"])
        if kind == "in":
            by_month[month]["in"] += amount
        else:
            by_month[month]["out"] -= amount
    return [{"m": m, **v, "net": v["in"] - v["out"]} for m, v in sorted(by_month.items())[-months:]]


def spending_by_category(transactions: list[dict[str, Any]], since: str) -> list[dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    for t in transactions:
        if t["transaction_date"] < since or _flow_kind(t) not in {"out", "refund"}:
            continue
        totals[t["category"] or "Outros"] -= int(t["amount_cents"])
    totals = {k: v for k, v in totals.items() if v > 0}
    total = sum(totals.values())
    return [
        {"label": k, "value": v, "pct": v / total}
        for k, v in sorted(totals.items(), key=lambda item: -item[1]) if total
    ]


YIELD_CATEGORY = "Rendimentos"
INCOME_EVENTS = {"DIVIDEND": "Dividendo", "JCP": "JCP", "INCOME": "Rendimento", "INTEREST": "Provento"}


def cdi_yield_settings() -> dict[str, float]:
    output = {}
    for r in rows("SELECT key, value FROM app_setting WHERE key LIKE 'cdi_pct:%'"):
        try:
            output[r["key"][len("cdi_pct:"):]] = float(r["value"])
        except ValueError:
            continue
    return output


def cdi_yield_pct(settings: dict[str, float], name: str, kind: str, institution: str | None) -> float:
    """% do CDI que o saldo em conta rende. Padrão: conta Nubank 100% (rende automaticamente); demais, 0."""
    if kind != "BANK":
        return 0.0
    if name in settings:
        return settings[name]
    return 100.0 if institution == "Nubank" else 0.0


def dividend_credits(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Créditos de proventos na conta, identificados pelo evento do ativo de mesmo valor em até 5 dias."""
    events = [dict(r) for r in rows(
        "SELECT e.event_date, e.event_type, e.amount_cents, i.ticker FROM investment_event e "
        "JOIN instrument i ON i.id = e.instrument_id WHERE e.event_type IN ('DIVIDEND', 'JCP', 'INCOME', 'INTEREST') "
        "AND e.amount_cents IS NOT NULL"
    )]
    free: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        free[abs(int(e["amount_cents"]))].append(e)
    output = []
    for t in sorted((t for t in transactions if t["category"] == "Proventos" and t["amount_cents"] > 0),
                    key=lambda t: t["transaction_date"], reverse=True):
        day = date.fromisoformat(t["transaction_date"])
        candidates = [e for e in free.get(int(t["amount_cents"]), [])
                      if abs((date.fromisoformat(e["event_date"]) - day).days) <= 5]
        match = min(candidates, key=lambda e: abs((date.fromisoformat(e["event_date"]) - day).days), default=None)
        if match:
            free[int(t["amount_cents"])].remove(match)
        output.append({
            "d": t["transaction_date"], "account": t["account_name"], "amount": int(t["amount_cents"]),
            "ticker": match["ticker"] if match else None,
            "kind": INCOME_EVENTS.get(match["event_type"], "Provento") if match else None,
            "description": t["description"],
        })
    return output


def month_start(offset: int = 0) -> str:
    today = date.today()
    year, month = today.year, today.month - offset
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1).isoformat()


def benchmark_payload(book: Book) -> dict[str, Any]:
    return {
        "cdi": [[d, book.cdi[d]] for d in book.cdi_dates],
        "ibov": [[d, v] for d, v in zip(book.ibov_dates, book.ibov_values)],
    }
