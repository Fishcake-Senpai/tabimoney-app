"""Operações dos agentes: cada função devolve o JSON (dict) que a CLI imprime e o servidor MCP responde.

Valores em reais, percentuais e pesos como fração (0.153 = 15,3%). `member` é o titular (id) ou None para a
casa toda; metas de gastos (orçamento) são sempre da casa. Erros de uso saem como ValueError (ou os erros dos
serviços), com a mensagem pronta para o usuário. Nada aqui apaga lançamentos.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app import db
from app.services import analytics, budgets, fundamentals, household, recommendations, spending, targets
from app.services.pension import parse_amount

# erros que viram {"erro": ...} na CLI e mensagem de erro no MCP
ERROS = (ValueError, fundamentals.FundamentalsError, recommendations.RecommendationError, budgets.BudgetError)


def _money(cents: int | None) -> float | None:
    return cents / 100 if cents is not None else None


def _member_names() -> dict[int, str]:
    return {m["id"]: m["name"] for m in household.members()}


def _tx(t: dict[str, Any], names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": t["id"], "data": t["transaction_date"], "descricao": t["description"], "valor": t["amount_cents"] / 100,
        "categoria": t["category"], "categoria_automatica": t.get("auto_category"), "origem_categoria": t.get("category_source"),
        "conta": t["account_name"], "tipo_conta": t["account_type"], "transferencia_com": t.get("transfer_with"),
        "titular": names.get(t.get("member_id", household.PRIMARY_ID)),
        **({"moeda_original": t["original_currency"], "valor_original": t["original_amount_cents"] / 100}
           if t.get("original_currency") else {}),
    }


# ---------------------------------------------------------------- gastos

def gastos_resumo(meses: int = 6, member: int | None = None) -> dict[str, Any]:
    trends = spending.category_trends(analytics.cash_transactions(member=member), window=meses)
    names = _member_names()
    return {
        "meses": trends["months"], "mes_corrente_incompleto": trends["months"][-1],
        "comparacao": f"{trends['last']} contra média de {', '.join(trends['base'])}",
        "categorias": [{
            "categoria": c["category"], "por_mes": dict(zip(trends["months"], [v / 100 for v in c["values"]])),
            "ultimo_mes": c["last"] / 100, "media_3m": c["avg3"] / 100, "variacao": c["delta"] / 100,
            "variacao_pct": c["delta_pct"], "tendencia_3m_vs_3m": c["trend_pct"], "ritmo_mes_corrente": c["current_pace"] / 100,
        } for c in trends["categories"]],
        "o_que_mudou": [{
            "categoria": c["category"], "variacao": c["delta"] / 100, "variacao_pct": c["delta_pct"],
            "principais_lancamentos": [_tx(t, names) for t in c.get("drivers", [])],
        } for c in trends["changes"]],
        "total_por_mes": dict(zip(trends["months"], [v / 100 for v in trends["totals"]])),
    }


def gastos_listar(mes: str | None = None, de: str | None = None, ate: str | None = None, categoria: str | None = None,
                  busca: str | None = None, conta: str | None = None, origem: str | None = None,
                  so_gastos: bool = False, limite: int = 200, deslocamento: int = 0, campos: list[str] | None = None,
                  member: int | None = None) -> dict[str, Any]:
    data = analytics.cash_transactions(member=member)
    if mes:
        data = [t for t in data if t["transaction_date"].startswith(mes)]
    if de:
        data = [t for t in data if t["transaction_date"] >= de]
    if ate:
        data = [t for t in data if t["transaction_date"] <= ate]
    if categoria:
        wanted = spending.normalize(categoria)
        data = [t for t in data if spending.normalize(t["category"] or "") == wanted]
    if busca:
        needle = spending.normalize(busca)
        data = [t for t in data if needle in spending.normalize(t["description"])]
    if conta:
        data = [t for t in data if spending.normalize(conta) in spending.normalize(t["account_name"])]
    if origem:
        data = [t for t in data if t.get("category_source") == origem]
    if so_gastos:
        data = [t for t in data if spending._spend_kind(t)]
    names = _member_names()
    page = [_tx(t, names) for t in data[deslocamento: deslocamento + limite]]
    if campos:
        keep = set(campos) | {"id"}
        page = [{k: v for k, v in t.items() if k in keep} for t in page]
    result: dict[str, Any] = {"total": len(data), "lancamentos": page}
    if deslocamento + limite < len(data):
        result["proximo_deslocamento"] = deslocamento + limite
    return result


def gastos_categorias() -> dict[str, Any]:
    return {"categorias": spending.known_categories(),
            "uso": spending.categories_overview(analytics.cash_transactions()),
            "excluidas": spending.deleted_categories(),
            "internas_fora_de_receita_e_despesa": sorted(analytics.INTERNAL_CATEGORIES)}


def gastos_criar_categoria(nome: str, autor: str = "agente") -> dict[str, Any]:
    return spending.create_category(nome, author=autor)


def gastos_excluir_categoria(nome: str, destino: str | None = None, autor: str = "agente") -> dict[str, Any]:
    """Levanta spending.CategoryInUse se a categoria está em uso e não veio destino (ver categoria_em_uso)."""
    return spending.delete_category(nome, destino, author=autor)


def categoria_em_uso(exc: spending.CategoryInUse, dica: str) -> dict[str, Any]:
    u = exc.usage
    return {"erro": str(exc), "lancamentos_corrigidos": u["manual"], "regras": [r["pattern"] for r in u["rules"]],
            "metas": [b["name"] for b in u["budgets"]], "dica": dica}


def gastos_restaurar_categoria(nome: str) -> dict[str, Any]:
    return spending.restore_category(nome)


def gastos_recategorizar(ids: list[int], categoria: str | None = None, automatica: bool = False) -> dict[str, Any]:
    category = None if automatica else categoria
    if not automatica and not category:
        raise ValueError("Informe a categoria ou peça a volta à automática.")
    changed = spending.set_category(ids, category)
    return {"alterados": changed, "categoria": spending.clean_category(category) if category else "automática"}


def gastos_regra(contem: str, categoria: str, conta: str | None = None, nota: str | None = None,
                 autor: str = "agente") -> dict[str, Any]:
    return spending.add_rule(contem, categoria, conta, author=autor, note=nota)


def gastos_regras() -> dict[str, Any]:
    return {"regras": spending.rules()}


def gastos_remover_regra(regra_id: int) -> dict[str, Any]:
    spending.delete_rule(regra_id)
    return {"removida": regra_id}


# ---------------------------------------------------------------- carteira, metas e fundamentos

def carteira_posicoes(member: int | None = None) -> dict[str, Any]:
    book = analytics.Book(member)
    output = []
    for a in book.assets():
        if a["qty"] <= 0:
            continue
        ind = fundamentals.indicators(a["iid"], a["close"])
        output.append({
            "ticker": a["ticker"], "nome": a["name"], "classe": a["asset_class"], "quantidade": a["qty"] / 1_000_000,
            "preco": a["close"] / 100 if a["close"] else None, "valor": a["value"] / 100 if a["value"] else None,
            "peso": a["weight"], "preco_medio": a["average_price"] / 100 if a["average_price"] else None,
            "preco_medio_status": a["cost_status"], "resultado_pct": a["unrealized_pct"], "proventos_12m": a["income_12m"] / 100,
            "fundamentos": ind["values"] if ind else None, "ultimo_balanco": ind["last_period"] if ind and ind["quarters"] else None,
        })
    return {
        "data": date.today().isoformat(), "posicoes": output,
        "renda_fixa": [{**p, "gross": p["gross"] / 100, "invested": (p["invested"] or 0) / 100} for p in book.fixed_income()],
        "previdencia": {k: v for k, v in book.pension().items() if k != "history"},
    }


def _targets_payload(book: analytics.Book, assets: list[dict[str, Any]], amount_text: str | None = None) -> dict[str, Any]:
    snap = targets.snapshot(book, assets)
    flow = analytics.cash_flow(analytics.cash_transactions(member=book.member) + book.yield_entries())
    suggested = targets.suggested_amount(flow)
    amount = parse_amount(amount_text, "o aporte", required=False) if amount_text else suggested
    t = snap["targets"]
    return {
        "metas": {"reserva_emergencia": _money(t["reserve_cents"]), "renda_fixa_pct": t["fixed_pct"],
                  "renda_variavel_pct": t["equity_pct"], "internacional_dentro_da_rv_pct": t["intl_pct"],
                  "previdencia_conta_como_renda_fixa": t["pension_in_fixed"],
                  "de": "casa" if t["member"] is None else ("titular" if t["own"] else "casa (titular sem metas próprias)")},
        "configurado": snap["configured"],
        "reserva": {"atual": _money(snap["reserve"]["value"]), "meta": _money(snap["reserve"]["target_value"]),
                    "falta": _money(snap["reserve"]["gap"]), "caixa_livre": _money(snap["reserve"]["free_cash"]),
                    "caixa_excedente_conta_como_rf": _money(snap["reserve"]["excess_cash"])},
        "investivel": _money(snap["investable"]),
        "classes": [{"classe": b["label"], "chave": b["key"], "atual": _money(b["value"]), "pct": b["pct"],
                     "meta_pct": b["target_pct"], "meta_valor": _money(b["target_value"]), "falta": _money(b["gap"]),
                     "desvio_pp": b["drift"]} for b in snap["buckets"]],
        "exposicao_por_ativo": [{"ticker": h["ticker"], "valor": _money(h["value"]), "regiao": h["region"],
                                 "regiao_definida_pelo_usuario": h["region_manual"]} for h in snap["holdings"]],
        "avisos": snap["alerts"],
        "aporte_para_equilibrar_sem_vender": _money(snap["rebalance_without_selling"]),
        "aporte_mensal_sugerido": _money(suggested),
        "plano_de_aporte": {"valor": _money(amount), "destino": [
            {"classe": p["label"], "chave": p["key"], "valor": _money(p["amount"]), "motivo": p["reason"],
             "pct_depois": p.get("pct_after")} for p in targets.contribution_plan(snap, amount or 0)]},
    }


def _amount_text(value: str | float | None) -> str | None:
    """Número vira texto com duas casas: parse_amount lê '12.345' como doze mil, como se escreve no Brasil."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return str(value)


def metas_mostrar(aporte: str | float | None = None, member: int | None = None) -> dict[str, Any]:
    book = analytics.Book(member)
    return _targets_payload(book, book.assets(), _amount_text(aporte))


def metas_definir(reserva: str | float | None = None, renda_fixa: float | None = None,
                  renda_variavel: float | None = None, internacional: float | None = None,
                  previdencia: bool | None = None, member: int | None = None) -> dict[str, Any]:
    """Percentuais de 0 a 100. Informar só renda fixa (ou só renda variável) completa a outra até 100."""
    current = targets.load(member)

    def pct(value: float | None, key: str) -> float | None:
        return value / 100 if value is not None else current[key]

    reserve = (parse_amount(_amount_text(reserva), "a reserva", required=False) if _amount_text(reserva)
               else current["reserve_cents"])
    fixed = pct(renda_fixa, "fixed_pct")
    equity = pct(renda_variavel, "equity_pct")
    if renda_fixa is not None and renda_variavel is None:
        equity = None
    if renda_variavel is not None and renda_fixa is None:
        fixed = None
    pension_flag = current["pension_in_fixed"] if previdencia is None else previdencia
    return targets.save(reserve, fixed, equity, pct(internacional, "intl_pct"), pension_flag, member=member)


def metas_regiao(ticker: str, regiao: str) -> dict[str, Any]:
    if regiao not in {"nacional", "internacional", "automatica"}:
        raise ValueError("A região é nacional, internacional ou automatica.")
    targets.set_region(ticker, None if regiao == "automatica" else regiao)
    return {"ticker": ticker.upper(), "regiao": regiao}


def carteira_contexto(aporte: str | float | None = None, member: int | None = None) -> dict[str, Any]:
    """Um JSON com tudo para recomendar: metas, posições com fundamentos, renda fixa, previdência, análises e avisos."""
    book = analytics.Book(member)
    assets = book.assets()
    regions = targets.regions()
    positions = []
    for a in assets:
        if a["qty"] <= 0:
            continue
        ind = fundamentals.indicators(a["iid"], a["close"])
        latest = fundamentals.reports(a["iid"], limit=1)
        positions.append({
            "ticker": a["ticker"], "nome": a["name"], "classe": a["asset_class"], "valor": _money(a["value"]),
            "peso_na_rv": a["weight"], "preco": _money(a["close"]), "preco_medio": _money(a["average_price"]),
            "resultado_pct": a["unrealized_pct"], "retorno_12m": a["r12m"], "proventos_12m": _money(a["income_12m"]),
            "regiao": regions.get(a["iid"], {}).get("region"),
            "setor": ind["profile"]["sector"] if ind else None,
            "fundamentos": ind["values"] if ind else None,
            "ultimo_balanco": ind["last_period"] if ind and ind["quarters"] else None,
            "avisos": [x["message"] for x in fundamentals.alerts(a["iid"])],
            "ultima_analise": {k: latest[0][k] for k in ("id", "period", "title", "summary", "verdict", "score", "created_at")}
            if latest else None,
        })
    rec = recommendations.get()
    kpis = book.portfolio_kpis(assets)
    return {
        "data": date.today().isoformat(),
        "titular": _member_names().get(member) if member is not None else "casa",
        "titulares": [m["name"] for m in household.members()],
        "metas_e_balanco": _targets_payload(book, assets, _amount_text(aporte)),
        "renda_variavel": {"valor": _money(kpis["value"]), "posicoes": positions,
                           "rentabilidade": kpis["returns"], "volatilidade_12m": kpis["volatility"]},
        "renda_fixa": [{"nome": p["name"], "tipo": p["product_type"], "indexador": p["indexer"], "taxa": p["rate"],
                        "vencimento": p["maturity"], "valor_bruto": _money(p["gross"]), "aplicado": _money(p["invested"])}
                       for p in book.fixed_income()],
        "previdencia": {k: v for k, v in book.pension().items() if k not in ("history", "plans")},
        "caixa": _money(book.cash_at(book.today)),
        "analises_sem_ticker": [{k: r[k] for k in ("id", "subject", "subject_type", "period", "title", "summary")}
                                for r in fundamentals.reports(limit=20) if not r["ticker"]],
        "recomendacao_anterior": {k: rec[k] for k in ("id", "period", "title", "summary", "created_at")} if rec else None,
        "unidades": "reais; percentuais e pesos como fração (0.15 = 15%)",
    }


def fundamentos_atualizar(tickers: list[str] | None = None) -> dict[str, Any]:
    return fundamentals.sync_fundamentals(tickers or None)


def fundamentos_contexto(ticker: str) -> dict[str, Any]:
    return fundamentals.agent_context(ticker)


# ---------------------------------------------------------------- análises, recomendações e avisos

def analise_importar(payload: Any, autor: str = "agente") -> dict[str, Any]:
    return fundamentals.import_analysis(payload, default_author=autor)


def analise_listar(ticker: str | None = None, tipo: str | None = None, limite: int = 20) -> dict[str, Any]:
    iid = None
    if ticker:
        found = db.rows("SELECT id FROM instrument WHERE ticker = ?", (ticker.upper(),))
        if not found:
            raise ValueError(f"{ticker} não está cadastrado.")
        iid = int(found[0][0])
    if tipo and tipo not in fundamentals.SUBJECT_TYPES:
        raise ValueError(f"Tipo inválido: {tipo}. Use {', '.join(fundamentals.SUBJECT_TYPES)}.")
    data = fundamentals.reports(iid, limite, subject_type=tipo)
    for r in data:
        r.pop("body_md", None)  # corpo completo: analise_mostrar
    return {"relatorios": data}


def analise_mostrar(relatorio_id: int) -> dict[str, Any]:
    found = fundamentals.reports(report_id=relatorio_id, limit=1)
    return found[0] if found else {"erro": "Relatório não encontrado."}


def recomendacoes_importar(payload: Any, autor: str = "agente") -> dict[str, Any]:
    return recommendations.import_recommendations(payload, default_author=autor)


def recomendacoes_listar() -> dict[str, Any]:
    return {"recomendacoes": recommendations.history()}


def recomendacoes_mostrar(recomendacao_id: int | None = None) -> dict[str, Any]:
    return recommendations.get(recomendacao_id) or {"erro": "Nenhuma recomendação."}


def alertas_listar(todos: bool = False) -> dict[str, Any]:
    return {"avisos": fundamentals.alerts(include_resolved=todos)}


def alertas_resolver(ids: list[int]) -> dict[str, Any]:
    for alert_id in ids:
        fundamentals.resolve_alert(alert_id)
    return {"resolvidos": ids}


# ---------------------------------------------------------------- orçamento (metas de gastos, sempre da casa)

def _budget_payload(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    st = budgets.status(transactions)
    return {
        "mes": st["month"], "dia": st["day"], "dias_no_mes": st["days_in_month"], "dias_restantes": st["days_left"],
        "limite_total": _money(st["total_limit"]), "gasto_nas_metas": _money(st["total_spent"]),
        "gasto_total_do_mes": _money(st["all_spent"]), "cabe_por_dia": _money(st["per_day"]),
        "metas_em_risco": st["at_risk"], "cobertura_das_metas": st["coverage"],
        "metas": [{
            "nome": i["name"], "categorias": i["categories"], "limite": _money(i["limit"]), "gasto_no_mes": _money(i["spent"]),
            "uso_pct": i["pct"], "projecao_mes": _money(i["projected"]), "projecao_pct": i["projected_pct"],
            "situacao": i["state"], "cabe_por_dia": _money(i["per_day"]), "media_3m": _money(i["avg3"]),
            "taxa_de_acerto": i["hit_rate"], "aviso_em_pct": i["alert_pct"], "autor": i["author"],
            "historico": [{"mes": h["m"], "gasto": _money(h["spent"]), "dentro_da_meta": h["hit"]} for h in i["history"]],
        } for i in st["items"]],
        "categorias_sem_meta": [{"categoria": u["category"], "gasto_no_mes": _money(u["spent"]), "media_3m": _money(u["avg3"])}
                                for u in st["uncovered"]],
    }


def orcamento_mostrar() -> dict[str, Any]:
    return _budget_payload(analytics.cash_transactions())


def orcamento_contexto(meses: int = 6) -> dict[str, Any]:
    """Tudo para a análise orçamentária: metas × gastos, tendência por categoria, renda e sugestões anteriores."""
    transactions = analytics.cash_transactions()
    book = analytics.Book()  # orçamento é da casa: ignora o titular
    flow = analytics.cash_flow(transactions + book.yield_entries())
    trends = spending.category_trends(transactions, window=meses)
    advice = budgets.latest_advice()
    names = _member_names()
    return {
        "orcamento": _budget_payload(transactions),
        "receitas_e_despesas_por_mes": [{"mes": m["m"], "receitas": _money(m["in"]), "despesas": _money(m["out"]),
                                         "sobra": _money(m["net"])} for m in flow[-meses - 1:]],
        "gasto_por_categoria": [{
            "categoria": c["category"], "por_mes": dict(zip(trends["months"], [v / 100 for v in c["values"]])),
            "media_3m": c["avg3"] / 100, "variacao_ultimo_mes_pct": c["delta_pct"], "tendencia_3m_vs_3m": c["trend_pct"],
        } for c in trends["categories"]],
        "o_que_mudou": [{"categoria": c["category"], "variacao": c["delta"] / 100,
                         "principais_lancamentos": [_tx(t, names) for t in c.get("drivers", [])]} for c in trends["changes"]],
        "metas_sugeridas_pela_media": [{"nome": s["name"], "categorias": s["categories"], "media_3m": _money(s["avg3"]),
                                        "limite_sugerido": _money(s["limit"])} for s in budgets.suggestions(transactions)],
        "recomendacao_anterior": {k: advice[k] for k in ("id", "period", "title", "summary", "created_at")} | {
            "itens": [{"acao": i["action"], "meta": i["budget_name"], "sugerido": _money(i["suggested_limit_cents"]),
                       "aplicada": bool(i["applied_at"])} for i in advice["items"]]} if advice else None,
        "reserva_e_aporte": _targets_payload(book, book.assets())["reserva"],
        "unidades": "reais; percentuais como fração (0.15 = 15%)",
    }


def orcamento_definir(nome: str, limite: str | float, categorias: list[str] | None = None, total: bool = False,
                      aviso: float | None = None, nota: str | None = None, autor: str = "agente") -> dict[str, Any]:
    categories = [budgets.TOTAL] if total else [c.strip() for c in (categorias or []) if c.strip()]
    limit = parse_amount(_amount_text(limite), "o limite mensal")
    return budgets.save_budget(nome, categories, limit, (aviso or 80) / 100, author=autor, note=nota)


def orcamento_remover(nome: str) -> dict[str, Any]:
    return {"removidas": budgets.delete_budget(name=nome)}


def orcamento_importar(payload: Any, autor: str = "agente") -> dict[str, Any]:
    return budgets.import_advice(payload, default_author=autor)


# ---------------------------------------------------------------- casa, backup e atualização

def titulares() -> dict[str, Any]:
    """Quem é quem: titulares, conexões (sem segredos) e contas de cada um."""
    accounts = db.rows(
        "SELECT account_name, institution, account_type, provider, COALESCE(member_id, 1) AS member_id "
        "FROM financial_account ORDER BY member_id, institution, account_name"
    )
    return {
        "titulares": [{
            "id": m["id"], "nome": m["name"], "principal": m["is_primary"], "cpf_cadastrado": m["has_document"],
            "contas": [{"conta": a["account_name"], "instituicao": a["institution"], "tipo": a["account_type"],
                        "origem": a["provider"]} for a in accounts if a["member_id"] == m["id"]],
        } for m in household.members()],
        "conexoes_pluggy": [{
            "id": c["id"], "nome": c["label"],
            "itens": [{"item": i["item_id"], "instituicao": i["institution"], "titular": i["member_name"]}
                      for i in c["items"]],
        } for c in household.connections()],
        "visao_da_casa": household.is_shared(),
    }


def backup() -> dict[str, Any]:
    return {"backup": str(db.create_backup())}


ETAPAS_ATUALIZAR = ("open_finance", "mercado", "fundamentos")


def atualizar(progresso: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Faz o que os botões do app fazem, em ordem: backup, Open Finance, mercado (cotações, IBOV, CDI) e CVM.
    Uma etapa com falha não impede as seguintes; o resultado de cada uma vem no JSON."""
    from app.services.sync import SyncError, sync_daily_quotes, sync_pluggy

    steps: dict[str, Any] = {"backup": str(db.create_backup())}
    for name, run in zip(ETAPAS_ATUALIZAR, (sync_pluggy, sync_daily_quotes, fundamentals.sync_fundamentals)):
        if progresso:
            progresso(name)
        try:
            result = run()
            steps[name] = {"status": result.get("status", "success"), "mensagem": result.get("message")}
        except (SyncError, fundamentals.FundamentalsError) as exc:
            steps[name] = {"status": "failed", "mensagem": str(exc)}
    steps["ok"] = all(s["status"] != "failed" for k, s in steps.items() if isinstance(s, dict))
    return steps


def ultimas_atualizacoes() -> dict[str, Any]:
    """Quando cada fonte foi atualizada pela última vez (para o agente saber se precisa atualizar)."""
    found = db.rows(
        "SELECT source, MAX(COALESCE(finished_at, started_at)) AS quando, "
        "(SELECT status FROM sync_run r2 WHERE r2.source = r.source ORDER BY r2.id DESC LIMIT 1) AS status "
        "FROM sync_run r GROUP BY source ORDER BY source"
    )
    return {r["source"]: {"quando": r["quando"], "situacao": r["status"]} for r in found}
