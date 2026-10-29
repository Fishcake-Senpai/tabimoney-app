"""Operações dos agentes: cada função devolve o JSON (dict) que a CLI imprime e o servidor MCP responde.

Valores em reais, percentuais e pesos como fração (0.153 = 15,3%). `member` é o titular (id) ou None para a
casa toda; metas de gastos (orçamento) são sempre da casa. Erros de uso saem como ValueError (ou os erros dos
serviços), com a mensagem pronta para o usuário. Nada aqui apaga lançamentos.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from app import db
from app.services import (analytics, budgets, fundamentals, household, investor_profile, recommendations, relatorio, spending,
                          targets)
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


def relatorio_exportar(periodo: str = "mes", referencia: str | None = None, arquivo: str | None = None,
                       mascarar: bool = True, extrato: bool = True, member: int | None = None) -> dict[str, Any]:
    """Grava o relatório do período (mês, trimestre ou ano) num HTML que abre sozinho. Sem `arquivo`, vai para a
    pasta Relatórios dos dados do app."""
    d = relatorio.montar(periodo, referencia, member, mascarar=mascarar, extrato=extrato)
    destino = Path(arquivo) if arquivo else db.data_dir() / "Relatorios" / relatorio.nome_arquivo(d["periodo"])
    if destino.is_dir() or not destino.suffix:  # uma pasta: o arquivo ganha o nome padrão dentro dela
        destino = destino / relatorio.nome_arquivo(d["periodo"])
    elif destino.suffix.lower() != ".html":
        destino = destino.with_suffix(".html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(relatorio.renderizar(d), encoding="utf-8")
    return {
        "arquivo": str(destino), "periodo": d["periodo"].ref, "titulo": d["periodo"].titulo,
        "em_andamento": d["em_andamento"], "receitas": _money(d["receitas"]), "gastos": _money(d["gastos"]),
        "sobra": _money(d["sobra"]), "investido": _money(d["investido"]), "resumo": d["resumo"],
        "mascarado": mascarar, "com_extrato": extrato,
    }


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


def perfil_investidor(member: int | None = None) -> dict[str, Any]:
    """Horizonte e objetivo do investidor. Sem perfil (ou vencido), as análises perguntam antes de começar."""
    p = investor_profile.load(member)
    return {
        "configurado": p["configured"], "horizonte": p["horizon"], "horizonte_texto": p["horizon_label"],
        "objetivo": p["goal"], "objetivo_texto": p["goal_label"], "atualizado_em": p["updated_at"], "vencido": p["stale"],
        "de": "casa" if member is None else ("titular" if p["own"] else "casa (titular sem perfil próprio)"),
        "opcoes": {"horizonte": investor_profile.HORIZONS, "objetivo": investor_profile.GOALS},
    }


def perfil_definir(horizonte: str, objetivo: str, member: int | None = None) -> dict[str, Any]:
    """Grava o perfil respondido pelo usuário (horizonte e objetivo da renda variável)."""
    investor_profile.save(horizonte, objetivo, member)
    return perfil_investidor(member)


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
        "perfil": perfil_investidor(member),
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


# ---------------------------------------------------------------- imposto de renda
# O IR é por pessoa: sem titular, vale o principal. Os serviços trabalham em centavos; aqui tudo vira reais.

_NAO_DINHEIRO = {"ano", "titular", "id", "instrumento", "ref_id", "exercicio", "member_id", "year", "first_month",
                 "last_month", "vacation_month", "thirteenth", "birth_year", "pendencias_bolsa", "payroll",
                 "transaction_id", "aportes", "meses", "n", "conferidos_ate_a_declaracao",
                 "lancamentos"}


def _reais(obj: Any, chave: str = "") -> Any:
    """Centavos → reais em todo o JSON; quantidades (milionésimos) → unidades. Chaves *_cents perdem o sufixo."""
    if isinstance(obj, dict):
        return {k.removesuffix("_cents"): _reais(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_reais(v, chave) for v in obj]
    if isinstance(obj, bool) or not isinstance(obj, int):
        return obj
    if chave in {"quantidade", "quantity_micros", "quantidade_sem_historico"}:
        return obj / 1_000_000
    if chave in _NAO_DINHEIRO:
        return obj
    return obj / 100


def _cents(valor: str | float | None, campo: str, obrigatorio: bool = True) -> int | None:
    if valor is None or valor == "":
        if obrigatorio:
            raise ValueError(f"Informe {campo}.")
        return None
    if isinstance(valor, (int, float)):
        if valor < 0:
            raise ValueError(f"Informe {campo} sem sinal negativo.")
        return int(round(valor * 100))
    return parse_amount(str(valor), campo, required=obrigatorio)


def _ir_membro(member: int | None) -> int:
    return member if member is not None else household.PRIMARY_ID


def _ano(ano: int | None) -> int:
    return int(ano or date.today().year)


def ir_contexto(ano: int | None = None, member: int | None = None) -> dict[str, Any]:
    """Tudo do IR do ano num JSON: perfil, estimativa, bolsa, deduções, previdência, pendências e o aviso de regras."""
    from app.services.ir import estimador, parametros, renda_variavel

    ano, m = _ano(ano), _ir_membro(member)
    est = estimador.estimar(m, ano)
    rv = renda_variavel.apurar(m, ano)
    ded = estimador.deducoes(m, ano)
    p = parametros.para(ano)
    return _reais({
        "ano": ano, "titular": _member_names().get(m), "aviso_regras": parametros.alerta_calendario(),
        "parametros": {"fonte": p.fonte, "a_confirmar": list(p.a_confirmar), "projetados": parametros.projetado(ano),
                       "conferidos_ate_a_declaracao": parametros.EXERCICIO_CONFIRMADO},
        "perfil": {"fontes": estimador.fontes(m, ano), "dependentes": estimador.dependentes(m, ano),
                   "contribui_previdencia_oficial": est["previdencia"]["contribui_previdencia_oficial"]},
        "estimativa": {k: est[k] for k in ("rendimentos_tributaveis", "inss", "irrf", "carne_leao", "deducoes", "modelos",
                                           "melhor", "devido", "saldo", "resultado", "previdencia", "dividendos", "irpfm",
                                           "decimo_terceiro", "obriga_declarar", "conciliacao")},
        "bolsa": {k: rv[k] for k in ("imposto_ano", "darf_total", "darfs", "pendencias", "bloqueado", "prejuizo_inicio",
                                     "prejuizo_fim", "isentos_linha_20", "irrf_sobra", "este_mes", "obriga_declarar")},
        "deducoes": {"itens": ded["itens"], "categorias_sugeridas_sem_tipo": ded["sugestoes"],
                     "categorias_com_tipo": ded["categorias"]},
        "previdencia": {"planos": estimador.planos(), "aportes": estimador.aportes(m, ano),
                        "sugestoes_de_aporte": estimador.sugestoes_aporte(m, ano)},
    })


def ir_acoes(ano: int | None = None, member: int | None = None) -> dict[str, Any]:
    from app.services.ir import renda_variavel

    return _reais(renda_variavel.apurar(_ir_membro(member), _ano(ano)))


def ir_estimativa(ano: int | None = None, pgbl_extra: str | float | None = None, member: int | None = None) -> dict[str, Any]:
    from app.services.ir import estimador

    return _reais(estimador.estimar(_ir_membro(member), _ano(ano), _cents(pgbl_extra, "o aporte extra", False) or 0))


def ir_declaracao(ano: int | None = None, member: int | None = None) -> dict[str, Any]:
    """Passo a passo da declaração do ano-calendário (padrão: o ano passado, que é o que se declara agora)."""
    from app.services.ir import declaracao

    return _reais(declaracao.montar(_ir_membro(member), int(ano) if ano else date.today().year - 1))


def ir_fonte(ano: int | None, tipo: str, pagador: str, bruto_mensal: str | float | None = None, cnpj: str | None = None,
             mes_inicio: int = 1, mes_fim: int = 12, decimo_terceiro: bool | None = None, mes_ferias: int | None = None,
             inss_mensal: str | float | None = None, irrf_ano: str | float | None = None,
             pensao_em_folha: str | float | None = None, faturamento_mensal: str | float | None = None,
             regime: str | None = None, lucro_mensal: str | float | None = None, fonte_id: int | None = None,
             remover: bool = False, member: int | None = None, autor: str = "agente") -> dict[str, Any]:
    """Cria, corrige ou remove uma fonte de renda (salário CLT, pró-labore ou outro rendimento tributável)."""
    from app.services.ir import estimador

    ano, m = _ano(ano), _ir_membro(member)
    if remover:
        if not fonte_id:
            raise ValueError("Informe fonte_id para remover.")
        estimador.remover_fonte(m, fonte_id)
        return _reais({"removida": fonte_id, "fontes": estimador.fontes(m, ano)})
    estimador.salvar_fonte(m, ano, {
        "kind": tipo, "payer": pagador, "payer_doc": cnpj, "gross_monthly_cents": _cents(bruto_mensal, "o bruto mensal"),
        "first_month": mes_inicio, "last_month": mes_fim,
        "thirteenth": (tipo == "clt") if decimo_terceiro is None else decimo_terceiro, "vacation_month": mes_ferias,
        "inss_monthly_cents": _cents(inss_mensal, "o INSS", False), "irrf_year_cents": _cents(irrf_ano, "o IRRF", False),
        "payroll_deductions_monthly_cents": _cents(pensao_em_folha, "a pensão", False) or 0,
        "pj_revenue_monthly_cents": _cents(faturamento_mensal, "o faturamento", False), "pj_regime": regime,
        "pj_profit_monthly_cents": _cents(lucro_mensal, "o lucro", False),
    }, fonte_id, autor)
    return _reais({"fontes": estimador.fontes(m, ano)})


def ir_dependente(ano: int | None, nome: str | None = None, parentesco: str = "filho", nascimento: int | None = None,
                  remover_id: int | None = None, member: int | None = None) -> dict[str, Any]:
    from app.services.ir import estimador

    ano, m = _ano(ano), _ir_membro(member)
    if remover_id:
        estimador.remover_dependente(m, remover_id)
    elif nome:
        estimador.salvar_dependente(m, ano, nome, parentesco, nascimento)
    else:
        raise ValueError("Informe o nome do dependente ou remover_id.")
    return {"dependentes": estimador.dependentes(m, ano)}


def ir_previdencia_oficial(ano: int | None, contribui: bool | None, member: int | None = None) -> dict[str, Any]:
    """Se o titular contribui para o INSS ou regime próprio (ou é aposentado por eles): condição do PGBL."""
    from app.services.ir import estimador

    return estimador.definir_perfil(_ir_membro(member), _ano(ano), contribui)


def ir_deducao_marcar(ids: list[int] | None = None, tipo: str | None = None, categoria: str | None = None,
                      beneficiario: str = "titular", prestador: str | None = None, documento: str | None = None,
                      subtipo: str | None = None, reembolso: str | float | None = None, pela_categoria: bool = False,
                      autor: str = "agente") -> dict[str, Any]:
    """Marca lançamentos (ids) ou uma categoria inteira como dedutível. tipo 'nenhuma' tira o lançamento; com
    pela_categoria o lançamento volta a seguir a categoria; categoria sem tipo tira o tipo da categoria."""
    from app.services.ir import estimador

    if categoria and not ids:
        return estimador.definir_categoria(categoria, tipo, autor)
    if not ids:
        raise ValueError("Informe ids de lançamentos ou uma categoria.")
    if pela_categoria:
        return estimador.desmarcar_lancamentos(ids)
    if not tipo:
        raise ValueError("Informe o tipo: saude, educacao, pensao, doacao ou nenhuma.")
    return estimador.marcar_lancamentos(ids, tipo, beneficiario, prestador, documento, subtipo,
                                        _cents(reembolso, "o reembolso", False) or 0, autor)


def ir_deducao_adicionar(data: str | None = None, tipo: str | None = None, valor: str | float | None = None,
                         prestador: str | None = None, documento: str | None = None, beneficiario: str = "titular",
                         subtipo: str | None = None, reembolso: str | float | None = None, nota: str | None = None,
                         remover_id: int | None = None, member: int | None = None, autor: str = "agente") -> dict[str, Any]:
    """Despesa dedutível paga fora das contas do app (dinheiro, conta de outra pessoa)."""
    from app.services.ir import estimador

    m = _ir_membro(member)
    if remover_id:
        estimador.remover_manual(m, remover_id)
        return {"removida": remover_id}
    return estimador.adicionar_manual(m, {
        "paid_on": data, "kind": tipo, "amount_cents": _cents(valor, "o valor"), "provider_name": prestador,
        "provider_doc": documento, "beneficiary": beneficiario, "subkind": subtipo,
        "reimbursed_cents": _cents(reembolso, "o reembolso", False) or 0, "note": nota}, autor)


def ir_pendencia_resolver(tipo: str, ticker: str | None = None, classe: str | None = None, valor: str | float | None = None,
                          periodo: str | None = None, grupo: str | None = None, conta: str | None = None,
                          ref_id: int | None = None, pago_em: str | None = None, member: int | None = None,
                          autor: str = "agente") -> dict[str, Any]:
    """Resolve uma pendência da apuração da bolsa: classe do ativo, custo de bonificação, prejuízo anterior, IRRF da
    nota, taxas do mês ou DARF pago."""
    from app.services.ir import renda_variavel

    m = _ir_membro(member)
    if tipo == "classe":
        if not ticker:
            raise ValueError("Informe o ticker.")
        return renda_variavel.definir_classe(ticker, classe)
    if tipo not in {"custo_bonificacao", "prejuizo_anterior", "irrf", "taxa", "darf_pago"}:
        raise ValueError(f"Tipo desconhecido: {tipo}. Use classe, custo_bonificacao, prejuizo_anterior, irrf, taxa ou darf_pago.")
    cents = _cents(valor, "o valor", tipo != "prejuizo_anterior") or 0
    return renda_variavel.informar(m, tipo, cents, period=periodo or "", grupo=grupo or "", conta=conta or "",
                                   ref_id=ref_id or 0, pago_em=pago_em, autor=autor)


def previdencia_aporte(plano: str, data: str, valor: str | float, pagador: str = "participante", folha: bool = False,
                       repetir_ate_dezembro: bool = False, autor: str = "agente") -> dict[str, Any]:
    """Registra um aporte de previdência, dizendo quem pagou (só o do participante deduz no PGBL)."""
    from app.services.ir import estimador

    alvo = spending.normalize(plano)
    found = next((p for p in estimador.planos() if p["product_key"] == plano or spending.normalize(p["name"]) == alvo), None)
    if not found:
        nomes = ", ".join(p["name"] for p in estimador.planos()) or "nenhum"
        raise ValueError(f"Plano não encontrado: {plano}. Planos: {nomes}.")
    return estimador.registrar_aporte(found["product_key"], data, _cents(valor, "o valor"), pagador, folha,
                                      repetir_ate_dezembro=repetir_ate_dezembro, autor=autor)
