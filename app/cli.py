"""Linha de comando para o usuário e para agentes de IA (Claude Code, Codex etc.).

    financas gastos resumo                      tendência por categoria e o que mudou
    financas gastos listar --mes 2026-08 --categoria Outros
    financas gastos recategorizar --id 812 813 --categoria Alimentação
    financas gastos regra --contem "PAGTO SALARIO" --categoria Salário
    financas fundamentos contexto EGIE3         tudo para analisar uma empresa, num JSON
    financas analise importar relatorio.json    grava relatórios, métricas e avisos do agente
    financas carteira contexto                  carteira + metas + fundamentos + últimas análises, num JSON
    financas metas mostrar --aporte 5000        balanço contra as metas e para onde vai o aporte
    financas recomendacoes importar recs.json   grava as recomendações trimestrais
    financas orcamento contexto                 metas de gastos × gastos, para a análise orçamentária
    financas orcamento importar-recomendacoes orc.json   grava as sugestões de orçamento do agente

Saída sempre em JSON (UTF-8), valores monetários em reais. Nada aqui apaga dados: correções ficam em
colunas/tabelas próprias e podem ser desfeitas. Contrato completo em docs/agente-financeiro.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from app import __version__, db
from app.services import analytics, budgets, fundamentals, recommendations, spending, targets
from app.services.pension import parse_amount


def _out(data: Any) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _tx(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"], "data": t["transaction_date"], "descricao": t["description"], "valor": t["amount_cents"] / 100,
        "categoria": t["category"], "categoria_automatica": t.get("auto_category"), "origem_categoria": t.get("category_source"),
        "conta": t["account_name"], "tipo_conta": t["account_type"], "transferencia_com": t.get("transfer_with"),
        **({"moeda_original": t["original_currency"], "valor_original": t["original_amount_cents"] / 100}
           if t.get("original_currency") else {}),
    }


# ---------------------------------------------------------------- gastos

def gastos_resumo(args: argparse.Namespace) -> None:
    trends = spending.category_trends(analytics.cash_transactions(), window=args.meses)
    _out({
        "meses": trends["months"], "mes_corrente_incompleto": trends["months"][-1],
        "comparacao": f"{trends['last']} contra média de {', '.join(trends['base'])}",
        "categorias": [{
            "categoria": c["category"], "por_mes": dict(zip(trends["months"], [v / 100 for v in c["values"]])),
            "ultimo_mes": c["last"] / 100, "media_3m": c["avg3"] / 100, "variacao": c["delta"] / 100,
            "variacao_pct": c["delta_pct"], "tendencia_3m_vs_3m": c["trend_pct"], "ritmo_mes_corrente": c["current_pace"] / 100,
        } for c in trends["categories"]],
        "o_que_mudou": [{
            "categoria": c["category"], "variacao": c["delta"] / 100, "variacao_pct": c["delta_pct"],
            "principais_lancamentos": [_tx(t) for t in c.get("drivers", [])],
        } for c in trends["changes"]],
        "total_por_mes": dict(zip(trends["months"], [v / 100 for v in trends["totals"]])),
    })


def gastos_listar(args: argparse.Namespace) -> None:
    data = analytics.cash_transactions()
    if args.mes:
        data = [t for t in data if t["transaction_date"].startswith(args.mes)]
    if args.de:
        data = [t for t in data if t["transaction_date"] >= args.de]
    if args.ate:
        data = [t for t in data if t["transaction_date"] <= args.ate]
    if args.categoria:
        wanted = spending.normalize(args.categoria)
        data = [t for t in data if spending.normalize(t["category"] or "") == wanted]
    if args.busca:
        needle = spending.normalize(args.busca)
        data = [t for t in data if needle in spending.normalize(t["description"])]
    if args.conta:
        data = [t for t in data if spending.normalize(args.conta) in spending.normalize(t["account_name"])]
    if args.origem:
        data = [t for t in data if t.get("category_source") == args.origem]
    if args.so_gastos:
        data = [t for t in data if spending._spend_kind(t)]
    _out({"total": len(data), "lancamentos": [_tx(t) for t in data[: args.limite]]})


def gastos_categorias(_: argparse.Namespace) -> None:
    _out({"categorias": spending.known_categories(),
          "uso": spending.categories_overview(analytics.cash_transactions()),
          "excluidas": spending.deleted_categories(),
          "internas_fora_de_receita_e_despesa": sorted(analytics.INTERNAL_CATEGORIES)})


def gastos_criar_categoria(args: argparse.Namespace) -> None:
    _out(spending.create_category(args.nome, author=args.autor))


def gastos_excluir_categoria(args: argparse.Namespace) -> None:
    try:
        _out(spending.delete_category(args.nome, args.destino, author=args.autor))
    except spending.CategoryInUse as exc:
        u = exc.usage
        _out({"erro": str(exc), "lancamentos_corrigidos": u["manual"], "regras": [r["pattern"] for r in u["rules"]],
              "metas": [b["name"] for b in u["budgets"]],
              "dica": "repita com --destino Outros (ou outra categoria, ou 'automatica')"})
        raise SystemExit(2)


def gastos_restaurar_categoria(args: argparse.Namespace) -> None:
    _out(spending.restore_category(args.nome))


def gastos_recategorizar(args: argparse.Namespace) -> None:
    category = None if args.automatica else args.categoria
    if not args.automatica and not category:
        raise SystemExit("Informe --categoria ou --automatica.")
    changed = spending.set_category(args.id, category)
    _out({"alterados": changed, "categoria": spending.clean_category(category) if category else "automática"})


def gastos_regra(args: argparse.Namespace) -> None:
    _out(spending.add_rule(args.contem, args.categoria, args.conta, author=args.autor, note=args.nota))


def gastos_regras(_: argparse.Namespace) -> None:
    _out({"regras": spending.rules()})


def gastos_remover_regra(args: argparse.Namespace) -> None:
    spending.delete_rule(args.id)
    _out({"removida": args.id})


# ---------------------------------------------------------------- carteira e fundamentos

def carteira_posicoes(_: argparse.Namespace) -> None:
    book = analytics.Book()
    assets = book.assets()
    output = []
    for a in assets:
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
    _out({
        "data": date.today().isoformat(), "posicoes": output,
        "renda_fixa": [{**p, "gross": p["gross"] / 100, "invested": (p["invested"] or 0) / 100} for p in book.fixed_income()],
        "previdencia": {k: v for k, v in book.pension().items() if k != "history"},
    })


def _money(cents: int | None) -> float | None:
    return cents / 100 if cents is not None else None


def _targets_payload(book, assets, amount_text: str | None = None) -> dict[str, Any]:
    snap = targets.snapshot(book, assets)
    flow = analytics.cash_flow(analytics.cash_transactions() + book.yield_entries())
    suggested = targets.suggested_amount(flow)
    amount = parse_amount(amount_text, "o aporte", required=False) if amount_text else suggested
    t = snap["targets"]
    return {
        "metas": {"reserva_emergencia": _money(t["reserve_cents"]), "renda_fixa_pct": t["fixed_pct"],
                  "renda_variavel_pct": t["equity_pct"], "internacional_dentro_da_rv_pct": t["intl_pct"],
                  "previdencia_conta_como_renda_fixa": t["pension_in_fixed"]},
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


def metas_mostrar(args: argparse.Namespace) -> None:
    book = analytics.Book()
    _out(_targets_payload(book, book.assets(), args.aporte))


def metas_definir(args: argparse.Namespace) -> None:
    current = targets.load()

    def pct(value: float | None, key: str) -> float | None:
        return value / 100 if value is not None else current[key]

    reserve = parse_amount(args.reserva, "a reserva", required=False) if args.reserva else current["reserve_cents"]
    fixed = pct(args.renda_fixa, "fixed_pct")
    equity = pct(args.renda_variavel, "equity_pct")
    if args.renda_fixa is not None and args.renda_variavel is None:
        equity = None
    if args.renda_variavel is not None and args.renda_fixa is None:
        fixed = None
    pension_flag = current["pension_in_fixed"] if args.previdencia is None else args.previdencia == "sim"
    _out(targets.save(reserve, fixed, equity, pct(args.internacional, "intl_pct"), pension_flag))


def metas_regiao(args: argparse.Namespace) -> None:
    targets.set_region(args.ticker, None if args.regiao == "automatica" else args.regiao)
    _out({"ticker": args.ticker.upper(), "regiao": args.regiao})


def carteira_contexto(args: argparse.Namespace) -> None:
    """Um JSON com tudo para recomendar: metas, posições com fundamentos, renda fixa, previdência, análises e avisos."""
    book = analytics.Book()
    assets = book.assets()
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
            "regiao": targets.regions().get(a["iid"], {}).get("region"),
            "setor": ind["profile"]["sector"] if ind else None,
            "fundamentos": ind["values"] if ind else None,
            "ultimo_balanco": ind["last_period"] if ind and ind["quarters"] else None,
            "avisos": [x["message"] for x in fundamentals.alerts(a["iid"])],
            "ultima_analise": {k: latest[0][k] for k in ("id", "period", "title", "summary", "verdict", "score", "created_at")}
            if latest else None,
        })
    rec = recommendations.get()
    kpis = book.portfolio_kpis(assets)
    _out({
        "data": date.today().isoformat(),
        "metas_e_balanco": _targets_payload(book, assets, args.aporte),
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
    })


def recomendacoes_importar(args: argparse.Namespace) -> None:
    raw = sys.stdin.read() if args.arquivo == "-" else open(args.arquivo, encoding="utf-8").read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"JSON inválido: {exc}") from exc
    _out(recommendations.import_recommendations(payload, default_author=args.autor))


def recomendacoes_listar(_: argparse.Namespace) -> None:
    _out({"recomendacoes": recommendations.history()})


def recomendacoes_mostrar(args: argparse.Namespace) -> None:
    _out(recommendations.get(args.id) or {"erro": "Nenhuma recomendação."})


def analise_mostrar(args: argparse.Namespace) -> None:
    found = fundamentals.reports(report_id=args.id, limit=1)
    _out(found[0] if found else {"erro": "Relatório não encontrado."})


def fundamentos_atualizar(args: argparse.Namespace) -> None:
    _out(fundamentals.sync_fundamentals(args.tickers or None))


def fundamentos_contexto(args: argparse.Namespace) -> None:
    _out(fundamentals.agent_context(args.ticker))


def analise_importar(args: argparse.Namespace) -> None:
    raw = sys.stdin.read() if args.arquivo == "-" else open(args.arquivo, encoding="utf-8").read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"JSON inválido: {exc}") from exc
    _out(fundamentals.import_analysis(payload, default_author=args.autor))


def analise_listar(args: argparse.Namespace) -> None:
    iid = None
    if args.ticker:
        found = db.rows("SELECT id FROM instrument WHERE ticker = ?", (args.ticker.upper(),))
        if not found:
            raise SystemExit(f"{args.ticker} não está cadastrado.")
        iid = int(found[0][0])
    data = fundamentals.reports(iid, args.limite, subject_type=args.tipo)
    for r in data:
        r.pop("body_md", None)  # corpo completo: financas analise mostrar ID
    _out({"relatorios": data})


def alertas_listar(args: argparse.Namespace) -> None:
    _out({"avisos": fundamentals.alerts(include_resolved=args.todos)})


def alertas_resolver(args: argparse.Namespace) -> None:
    for alert_id in args.id:
        fundamentals.resolve_alert(alert_id)
    _out({"resolvidos": args.id})


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


def orcamento_mostrar(_: argparse.Namespace) -> None:
    _out(_budget_payload(analytics.cash_transactions()))


def orcamento_contexto(args: argparse.Namespace) -> None:
    """Tudo para a análise orçamentária: metas × gastos, tendência por categoria, renda e sugestões anteriores."""
    transactions = analytics.cash_transactions()
    book = analytics.Book()
    flow = analytics.cash_flow(transactions + book.yield_entries())
    trends = spending.category_trends(transactions, window=args.meses)
    advice = budgets.latest_advice()
    _out({
        "orcamento": _budget_payload(transactions),
        "receitas_e_despesas_por_mes": [{"mes": m["m"], "receitas": _money(m["in"]), "despesas": _money(m["out"]),
                                         "sobra": _money(m["net"])} for m in flow[-args.meses - 1:]],
        "gasto_por_categoria": [{
            "categoria": c["category"], "por_mes": dict(zip(trends["months"], [v / 100 for v in c["values"]])),
            "media_3m": c["avg3"] / 100, "variacao_ultimo_mes_pct": c["delta_pct"], "tendencia_3m_vs_3m": c["trend_pct"],
        } for c in trends["categories"]],
        "o_que_mudou": [{"categoria": c["category"], "variacao": c["delta"] / 100,
                         "principais_lancamentos": [_tx(t) for t in c.get("drivers", [])]} for c in trends["changes"]],
        "metas_sugeridas_pela_media": [{"nome": s["name"], "categorias": s["categories"], "media_3m": _money(s["avg3"]),
                                        "limite_sugerido": _money(s["limit"])} for s in budgets.suggestions(transactions)],
        "recomendacao_anterior": {k: advice[k] for k in ("id", "period", "title", "summary", "created_at")} | {
            "itens": [{"acao": i["action"], "meta": i["budget_name"], "sugerido": _money(i["suggested_limit_cents"]),
                       "aplicada": bool(i["applied_at"])} for i in advice["items"]]} if advice else None,
        "reserva_e_aporte": _targets_payload(book, book.assets())["reserva"],
        "unidades": "reais; percentuais como fração (0.15 = 15%)",
    })


def orcamento_definir(args: argparse.Namespace) -> None:
    categories = [budgets.TOTAL] if args.total else [c.strip() for c in (args.categorias or "").split(",") if c.strip()]
    limit = parse_amount(args.limite, "o limite mensal")
    _out(budgets.save_budget(args.nome, categories, limit, (args.aviso or 80) / 100, author=args.autor, note=args.nota))


def orcamento_remover(args: argparse.Namespace) -> None:
    _out({"removidas": budgets.delete_budget(name=args.nome)})


def orcamento_importar(args: argparse.Namespace) -> None:
    raw = sys.stdin.read() if args.arquivo == "-" else open(args.arquivo, encoding="utf-8").read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"JSON inválido: {exc}") from exc
    _out(budgets.import_advice(payload, default_author=args.autor))


def backup(_: argparse.Namespace) -> None:
    _out({"backup": str(db.create_backup())})


def atualizar(_: argparse.Namespace) -> None:
    """Faz o que os botões do app fazem, em ordem: backup, Open Finance, mercado (cotações, IBOV, CDI) e CVM.
    Uma etapa com falha não impede as seguintes; o resultado de cada uma vem no JSON."""
    from app.services.sync import SyncError, sync_daily_quotes, sync_pluggy

    steps: dict[str, Any] = {"backup": str(db.create_backup())}
    for name, run in (("open_finance", sync_pluggy), ("mercado", sync_daily_quotes),
                      ("fundamentos", fundamentals.sync_fundamentals)):
        try:
            result = run()
            steps[name] = {"status": result.get("status", "success"), "mensagem": result.get("message")}
        except (SyncError, fundamentals.FundamentalsError) as exc:
            steps[name] = {"status": "failed", "mensagem": str(exc)}
    steps["ok"] = all(s["status"] != "failed" for k, s in steps.items() if isinstance(s, dict))
    _out(steps)


# ---------------------------------------------------------------- argumentos

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financas", description="Tabimoney: finanças pessoais locais (saída em JSON).")
    parser.add_argument("--version", action="version", version=f"Tabimoney {__version__}")
    groups = parser.add_subparsers(dest="grupo", required=True)

    g = groups.add_parser("gastos", help="movimentações, categorias e regras").add_subparsers(dest="acao", required=True)
    p = g.add_parser("resumo", help="gasto por categoria mês a mês e o que mudou")
    p.add_argument("--meses", type=int, default=6)
    p.set_defaults(func=gastos_resumo)
    p = g.add_parser("listar", help="lista lançamentos com filtros")
    p.add_argument("--mes", help="AAAA-MM")
    p.add_argument("--de", help="AAAA-MM-DD")
    p.add_argument("--ate", help="AAAA-MM-DD")
    p.add_argument("--categoria")
    p.add_argument("--busca", help="texto na descrição")
    p.add_argument("--conta")
    p.add_argument("--origem", choices=["auto", "regra", "manual"], help="de onde veio a categoria")
    p.add_argument("--so-gastos", action="store_true", help="só o que entra em despesas")
    p.add_argument("--limite", type=int, default=200)
    p.set_defaults(func=gastos_listar)
    g.add_parser("categorias", help="categorias existentes, uso de cada uma e excluídas").set_defaults(func=gastos_categorias)
    p = g.add_parser("criar-categoria", help="cria uma categoria (idempotente: se já existe, devolve a existente)")
    p.add_argument("nome")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=gastos_criar_categoria)
    p = g.add_parser("excluir-categoria", help="exclui uma categoria própria; em uso, exige --destino")
    p.add_argument("nome")
    p.add_argument("--destino", help="categoria que recebe lançamentos, regras e metas, ou 'automatica'")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=gastos_excluir_categoria)
    p = g.add_parser("restaurar-categoria", help="desfaz a exclusão de uma categoria")
    p.add_argument("nome")
    p.set_defaults(func=gastos_restaurar_categoria)
    p = g.add_parser("recategorizar", help="corrige a categoria de lançamentos")
    p.add_argument("--id", type=int, nargs="+", required=True)
    p.add_argument("--categoria")
    p.add_argument("--automatica", action="store_true", help="volta à categoria automática")
    p.set_defaults(func=gastos_recategorizar)
    p = g.add_parser("regra", help="cria/atualiza regra 'descrição contém X → categoria'")
    p.add_argument("--contem", required=True)
    p.add_argument("--categoria", required=True)
    p.add_argument("--conta")
    p.add_argument("--nota")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=gastos_regra)
    g.add_parser("regras", help="lista regras").set_defaults(func=gastos_regras)
    p = g.add_parser("remover-regra")
    p.add_argument("id", type=int)
    p.set_defaults(func=gastos_remover_regra)

    g = groups.add_parser("carteira", help="posições com fundamentos").add_subparsers(dest="acao", required=True)
    g.add_parser("posicoes").set_defaults(func=carteira_posicoes)
    p = g.add_parser("contexto", help="tudo para recomendar: metas, posições, fundamentos, análises")
    p.add_argument("--aporte", help="valor do próximo aporte em reais")
    p.set_defaults(func=carteira_contexto)

    g = groups.add_parser("fundamentos", help="dados da CVM e indicadores").add_subparsers(dest="acao", required=True)
    p = g.add_parser("atualizar", help="baixa ITR/DFP da CVM e recalcula avisos")
    p.add_argument("tickers", nargs="*")
    p.set_defaults(func=fundamentos_atualizar)
    p = g.add_parser("contexto", help="tudo o que um agente precisa para analisar uma empresa")
    p.add_argument("ticker")
    p.set_defaults(func=fundamentos_contexto)

    g = groups.add_parser("analise", help="relatórios do agente").add_subparsers(dest="acao", required=True)
    p = g.add_parser("importar", help="grava relatório/métricas/avisos (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=analise_importar)
    p = g.add_parser("listar", help="lista relatórios (sem o corpo)")
    p.add_argument("--ticker")
    p.add_argument("--tipo", choices=list(fundamentals.SUBJECT_TYPES))
    p.add_argument("--limite", type=int, default=20)
    p.set_defaults(func=analise_listar)
    p = g.add_parser("mostrar", help="relatório completo")
    p.add_argument("id", type=int)
    p.set_defaults(func=analise_mostrar)

    g = groups.add_parser("metas", help="metas de alocação e aporte").add_subparsers(dest="acao", required=True)
    p = g.add_parser("mostrar", help="balanço contra as metas e distribuição do aporte")
    p.add_argument("--aporte", help="valor em reais (padrão: média de sobra mensal)")
    p.set_defaults(func=metas_mostrar)
    p = g.add_parser("definir", help="grava metas (percentuais de 0 a 100)")
    p.add_argument("--reserva", help="reserva de emergência em reais")
    p.add_argument("--renda-fixa", type=float)
    p.add_argument("--renda-variavel", type=float)
    p.add_argument("--internacional", type=float, help="%% da renda variável no exterior")
    p.add_argument("--previdencia", choices=["sim", "nao"], help="conta a previdência como renda fixa")
    p.set_defaults(func=metas_definir)
    p = g.add_parser("regiao", help="define se um ativo é exposição nacional ou internacional")
    p.add_argument("ticker")
    p.add_argument("regiao", choices=["nacional", "internacional", "automatica"])
    p.set_defaults(func=metas_regiao)

    g = groups.add_parser("recomendacoes", help="recomendações trimestrais").add_subparsers(dest="acao", required=True)
    p = g.add_parser("importar", help="grava o conjunto do trimestre (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=recomendacoes_importar)
    g.add_parser("listar").set_defaults(func=recomendacoes_listar)
    p = g.add_parser("mostrar")
    p.add_argument("id", type=int, nargs="?")
    p.set_defaults(func=recomendacoes_mostrar)

    g = groups.add_parser("alertas", help="avisos de fundamentos").add_subparsers(dest="acao", required=True)
    p = g.add_parser("listar")
    p.add_argument("--todos", action="store_true", help="inclui os já vistos")
    p.set_defaults(func=alertas_listar)
    p = g.add_parser("resolver")
    p.add_argument("id", type=int, nargs="+")
    p.set_defaults(func=alertas_resolver)

    g = groups.add_parser("orcamento", help="metas de gastos e recomendações orçamentárias").add_subparsers(dest="acao", required=True)
    g.add_parser("mostrar", help="mês corrente contra cada meta de gasto").set_defaults(func=orcamento_mostrar)
    p = g.add_parser("contexto", help="tudo para a análise orçamentária do agente")
    p.add_argument("--meses", type=int, default=6)
    p.set_defaults(func=orcamento_contexto)
    p = g.add_parser("definir", help="cria ou atualiza uma meta de gasto (só com pedido do usuário)")
    p.add_argument("--nome", required=True)
    p.add_argument("--categorias", help="lista separada por vírgula (ex.: 'Alimentação,Mercado')")
    p.add_argument("--total", action="store_true", help="meta de todos os gastos do mês")
    p.add_argument("--limite", required=True, help="limite mensal em reais")
    p.add_argument("--aviso", type=float, help="%% do limite que dispara o aviso (padrão 80)")
    p.add_argument("--nota")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=orcamento_definir)
    p = g.add_parser("remover", help="remove uma meta de gasto (só com pedido do usuário)")
    p.add_argument("--nome", required=True)
    p.set_defaults(func=orcamento_remover)
    p = g.add_parser("importar-recomendacoes", help="grava as sugestões orçamentárias do mês (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")
    p.set_defaults(func=orcamento_importar)

    groups.add_parser("backup", help="cópia da base antes de mudanças em massa").set_defaults(func=backup)
    groups.add_parser("atualizar", help="backup + Open Finance + cotações/CDI + balanços da CVM").set_defaults(func=atualizar)
    return parser


def main(argv: list[str] | None = None) -> None:
    db.init_db()
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ValueError, fundamentals.FundamentalsError, recommendations.RecommendationError, budgets.BudgetError) as exc:
        _out({"erro": str(exc)})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
