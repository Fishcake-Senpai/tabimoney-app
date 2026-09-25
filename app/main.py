from __future__ import annotations

import hmac
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.security import delete_secret, get_secret, save_secret
from app import __version__
from app.services import analytics, budgets, fundamentals, pension, recommendations, spending, targets
from app.services.categories import INCOME_CATEGORIES, INTERNAL_CATEGORIES
from app.services.markdown import render as render_markdown
from app.services.formatting import (
    brl, brl_compact, brl_signed, brl_whole, date_br, foreign_money, indicator, metric_value, month_label, multiple, pct,
    quantity, tone,
)
from app.services.importers import import_ofx, import_positions_csv, import_quotes_csv, normalize_ticker
from app.services.smart_import import import_file
from app.services.sync import SyncError, parse_item_ids, pluggy_item_ids, quote_scheduler, sync_daily_quotes, sync_pluggy

APP_DIR = Path(__file__).resolve().parent
PORT = 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").lower()
        remote = request.client.host if request.client else ""
        if host not in ALLOWED_HOSTS or remote not in {"127.0.0.1", "::1"}:
            return PlainTextResponse("Este aplicativo só aceita conexões locais.", status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != "null" and origin not in {
                f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"
            }:
                return PlainTextResponse("Origem não permitida.", status_code=403)
            # Browser Fetch Metadata can report loopback/embedded form posts as cross-site.
            # Every state-changing route also validates a session-bound CSRF token.
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    stop_event = threading.Event()
    worker = threading.Thread(target=quote_scheduler, args=(stop_event,), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop_event.set()
        worker.join(timeout=2)


app = FastAPI(title="Tabimoney", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(LocalOnlyMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=secrets.token_urlsafe(48),
    session_cookie="financas_local_session",
    same_site="strict",
    https_only=False,
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    # os navegadores pedem o ícone na raiz mesmo com <link rel="icon">
    return FileResponse(APP_DIR / "static" / "brand" / "favicon.ico", media_type="image/x-icon")


# ---------------------------------------------------------------- encerrar (launcher e botão)

def _schedule_shutdown(request: Request) -> bool:
    """Pede ao uvicorn para sair depois de responder. Só existe quando o app foi aberto pelo launcher."""
    server = getattr(request.app.state, "server", None)
    if server is None:
        return False
    threading.Timer(0.4, lambda: setattr(server, "should_exit", True)).start()
    return True


@app.post("/_sistema/encerrar", include_in_schema=False)
def shutdown_from_launcher(request: Request):
    """Chamado pelo Tabimoney.exe ao ser aberto de novo; o token vem do arquivo de trava local."""
    expected = str(getattr(request.app.state, "shutdown_token", "") or "")
    if not expected or not hmac.compare_digest(expected, request.headers.get("x-tabimoney-token", "")):
        raise HTTPException(status_code=403)
    _schedule_shutdown(request)
    return PlainTextResponse("encerrando")


@app.post("/sistema/encerrar", response_class=HTMLResponse)
def shutdown_from_user(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    if not _schedule_shutdown(request):
        _flash(request, "warning", "Este Tabimoney foi aberto pelo terminal: encerre com Ctrl+C na janela dele.")
        return _redirect(request, "/configuracoes")
    return _render(request, "closed.html")


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["brl"] = brl
templates.env.filters["brl_signed"] = brl_signed
templates.env.filters["brl_compact"] = brl_compact
templates.env.filters["brl_whole"] = brl_whole
templates.env.filters["pct"] = pct
templates.env.filters["date_br"] = date_br
templates.env.filters["month_label"] = month_label
templates.env.filters["tone"] = tone
templates.env.filters["foreign_money"] = foreign_money
templates.env.filters["quantity"] = quantity
templates.env.filters["multiple"] = multiple
templates.env.filters["indicator"] = indicator
templates.env.filters["md"] = render_markdown
templates.env.globals["app_version"] = __version__
templates.env.filters["metric_value"] = metric_value


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _check_csrf(request: Request, submitted: str) -> None:
    expected = str(request.session.get("csrf_token", ""))
    if not expected or not hmac.compare_digest(expected, submitted or ""):
        raise HTTPException(status_code=403, detail="Formulário expirado. Atualize a página e tente novamente.")


def _flash(request: Request, kind: str, message: str) -> None:
    messages = list(request.session.get("flash_messages", []))
    messages.append({"kind": kind, "text": message})
    request.session["flash_messages"] = messages[-8:]


def _render(request: Request, template: str, **context):
    messages = request.session.pop("flash_messages", [])
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"csrf_token": _csrf_token(request), "flash_messages": messages, **context},
    )


def _redirect(request: Request, path: str = "/") -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _secret_configured(key: str) -> str:
    try:
        return "Configurada" if get_secret(key) else "Não configurada"
    except Exception:
        return "Cofre do Windows indisponível"


def _nav_counts() -> dict[str, int]:
    pending = db.rows(
        "SELECT (SELECT COUNT(*) FROM v_position_reconciliation WHERE status = 'DIVERGENT') "
        "+ (SELECT COUNT(*) FROM v_bank_balance_reconciliation WHERE status = 'DIVERGENT') AS n"
    )
    return {"pending": int(pending[0]["n"]) if pending else 0}


def _page(request: Request, template: str, **context):
    return _render(request, template, nav=_nav_counts(), **context)


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    book = analytics.Book()
    assets = book.assets()
    kpis = book.portfolio_kpis(assets)
    series = book.series()
    transactions = analytics.cash_transactions()
    flow = analytics.cash_flow(transactions + book.yield_entries())
    fixed = book.fixed_income()
    accounts = book.accounts()
    last = series[-1] if series else None
    month_ago = next((p for p in reversed(series) if last and p["d"] <= analytics._shift(last["d"], 30)), None)
    flow_by_month = {row["m"]: row for row in flow}
    previous = flow_by_month.get(analytics.month_start(1)[:7])
    card = [a for a in accounts if a["type"] == "CREDIT"]
    movers = sorted(
        (a for a in assets if a["day_pct"] is not None and a["qty"] > 0), key=lambda a: -abs(a["day_pct"])
    )[:5]
    summary = {
        "net_worth": last["nw"] if last else None,
        "change_30d": last["nw"] - month_ago["nw"] if last and month_ago else None,
        "change_30d_pct": analytics._pct(last["nw"] - month_ago["nw"], month_ago["nw"]) if last and month_ago else None,
        "equity": kpis["value"], "fixed": sum(p["gross"] for p in fixed), "cash": book.cash_at(book.today),
        "pension": book.pension_at(book.today) or None,
        "card_due": -sum(a["balance"] for a in card) if card else None,
        "card_available": sum(a["available"] or 0 for a in card) if any(a["available"] for a in card) else None,
        "spend_month": flow_by_month.get(analytics.month_start(0)[:7], {}).get("out"),
        "spend_prev": previous["out"] if previous else None,
        "savings_rate": analytics._pct(previous["net"], previous["in"]) if previous and previous["in"] else None,
    }
    balance = targets.snapshot(book, assets)
    budget = budgets.status(transactions)
    return _page(
        request, "overview.html", summary=summary, kpis=kpis, movers=movers, balance=balance,
        display_name=db.get_setting("display_name"), budget=budget,
        allocation=book.allocation(assets),
        categories=analytics.spending_by_category(transactions, analytics.month_start(0))[:8],
        chart_series=[{k: p[k] for k in ("d", "eq", "fi", "pv", "cash", "debt", "nw")} for p in series],
        chart_flow=flow, has_data=bool(series or transactions),
    )


@app.get("/carteira", response_class=HTMLResponse)
def portfolio(request: Request):
    book = analytics.Book()
    assets = book.assets()
    kpis = book.portfolio_kpis(assets)
    series = book.series()
    return _page(
        request, "portfolio.html", assets=assets, kpis=kpis, allocation=book.allocation(assets),
        fund=fundamentals.portfolio_fundamentals(assets), fund_alerts=fundamentals.alerts(),
        indicator_meta=fundamentals.INDICATORS, fund_synced=db.get_setting("fundamentals_synced_at"),
        chart_returns={
            "series": [{"d": p["d"], "r": p["r"]} for p in series if p["eq"] or p["r"]],
            **analytics.benchmark_payload(book),
        },
        chart_value=[{"d": p["d"], "eq": p["eq"], "cap": p["cap"]} for p in series if p["eq"] or p["cap"]],
        monthly=book.monthly_returns(12),
    )


@app.get("/ativo/{ticker}", response_class=HTMLResponse)
def asset_page(request: Request, ticker: str):
    normalized = normalize_ticker(ticker)
    book = analytics.Book()
    asset = next((a for a in book.assets() if a["ticker"] == normalized), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado na carteira.")
    history = book.asset_history(asset["iid"])
    ind = fundamentals.indicators(asset["iid"], asset["close"])
    quarters = ind["quarters"][-12:] if ind else []
    return _page(
        request, "asset.html", asset=asset, events=history["events"],
        chart_price={"prices": history["prices"], "avg": asset["average_price"]},
        ind=ind, quarters=list(reversed(quarters[-8:])), indicator_meta=fundamentals.INDICATORS,
        fund_alerts=fundamentals.alerts(asset["iid"]), reports=fundamentals.reports(asset["iid"], limit=50),
        filings=fundamentals.filings(asset["iid"]), agent_metrics=fundamentals.agent_metrics(asset["iid"]),
        chart_quarters=[
            {"m": q["label"],
             "revenue": round(q["revenue"] * 100) if q.get("revenue") is not None else None,
             "net_income": round(q["net_income"] * 100) if q.get("net_income") is not None else None}
            for q in quarters
        ],
    )


@app.get("/metas", response_class=HTMLResponse)
def targets_page(request: Request, aporte: str = ""):
    book = analytics.Book()
    assets = book.assets()
    snap = targets.snapshot(book, assets)
    flow = analytics.cash_flow(analytics.cash_transactions() + book.yield_entries())
    suggested = targets.suggested_amount(flow)
    try:
        amount = pension.parse_amount(aporte, "o aporte", required=False) if aporte else suggested
    except ValueError as exc:
        _flash(request, "error", str(exc))
        amount = suggested
    return _page(
        request, "targets.html", snap=snap, plan=targets.contribution_plan(snap, amount or 0), amount=amount,
        suggested=suggested, recommendation=recommendations.get(),
    )


@app.post("/metas")
def save_targets(request: Request, csrf_token: str = Form(...), reserve: str = Form(""), fixed_pct: str = Form(""),
                 equity_pct: str = Form(""), intl_pct: str = Form(""), pension_in_fixed: str = Form("")):
    _check_csrf(request, csrf_token)

    def pct_value(raw: str, label: str) -> float | None:
        text = raw.strip().replace("%", "").replace(",", ".")
        if not text:
            return None
        try:
            return float(text) / 100
        except ValueError as exc:
            raise ValueError(f"Percentual inválido para {label}: {raw}.") from exc

    try:
        targets.save(
            pension.parse_amount(reserve, "a reserva", required=False),
            pct_value(fixed_pct, "renda fixa"), pct_value(equity_pct, "renda variável"),
            pct_value(intl_pct, "internacional"), pension_in_fixed == "on",
        )
        _flash(request, "success", "Metas salvas.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/metas")


@app.post("/metas/regiao")
def save_region(request: Request, csrf_token: str = Form(...), ticker: str = Form(...), region: str = Form("")):
    _check_csrf(request, csrf_token)
    try:
        targets.set_region(ticker, region or None)
        _flash(request, "success", f"{ticker}: exposição {region or 'automática'}.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/metas#exposicao")


@app.get("/recomendacoes", response_class=HTMLResponse)
def recommendations_page(request: Request, id: int | None = None):
    book = analytics.Book()
    assets = book.assets()
    current = recommendations.get(id)
    weights = {a["ticker"]: a["weight"] or 0 for a in assets if a["qty"] > 0}
    if current:
        for portfolio in current["portfolios"]:
            portfolio["compare"] = recommendations.compare_with_holdings(portfolio, weights)
    return _page(
        request, "recommendations.html", current=current, history=recommendations.history(), weights=weights,
        advice=budgets.latest_advice(), advice_history=budgets.advice_history(),
        budget=budgets.status(analytics.cash_transactions()),
        held={a["ticker"] for a in assets if a["qty"] > 0}, labels=recommendations.ACTION_LABELS,
        snap=targets.snapshot(book, assets),
    )


@app.get("/analises", response_class=HTMLResponse)
def reports_page(request: Request, ticker: str = "", tipo: str = ""):
    iid = None
    if ticker:
        found = db.rows("SELECT id FROM instrument WHERE ticker = ?", (ticker.upper(),))
        iid = int(found[0][0]) if found else -1
    return _page(
        request, "reports.html", reports=fundamentals.reports(iid, limit=300, subject_type=tipo or None),
        ticker=ticker.upper(), tipo=tipo, subject_types=fundamentals.SUBJECT_TYPES,
    )


@app.get("/analises/{report_id}", response_class=HTMLResponse)
def report_page(request: Request, report_id: int):
    found = fundamentals.reports(report_id=report_id, limit=1)
    if not found:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    report = found[0]
    siblings = fundamentals.reports(report["instrument_id"], limit=50) if report["instrument_id"] else []
    return _page(request, "report.html", report=report, siblings=siblings)


@app.post("/fundamentos/atualizar")
def fundamentals_sync(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        result = fundamentals.sync_fundamentals()
        _flash(request, "success", result["message"])
    except fundamentals.FundamentalsError as exc:
        _flash(request, "error", f"Fundamentos: {exc}")
    return _redirect(request, "/carteira")


@app.post("/alertas/resolver")
def alert_resolve(request: Request, csrf_token: str = Form(...), alert_id: int = Form(...), back: str = Form("/carteira")):
    _check_csrf(request, csrf_token)
    fundamentals.resolve_alert(alert_id)
    _flash(request, "success", "Aviso marcado como visto.")
    return _redirect(request, back if back.startswith("/") and not back.startswith("//") else "/carteira")


@app.get("/renda-fixa", response_class=HTMLResponse)
def fixed_income_page(request: Request):
    book = analytics.Book()
    products = book.fixed_income()
    by_type: dict[str, int] = {}
    for p in products:
        by_type[p["product_type"]] = by_type.get(p["product_type"], 0) + p["gross"]
    total = sum(by_type.values())
    known = [p for p in products if p["invested"]]
    invested = sum(p["invested"] for p in known)
    gain = sum(p["gain"] for p in known)
    upcoming = sorted(
        (p for p in products if p["days_to_maturity"] is not None and p["days_to_maturity"] >= 0),
        key=lambda p: p["days_to_maturity"],
    )
    return _page(
        request, "fixed_income.html", products=products,
        reports=fundamentals.reports(subject_type="renda_fixa", limit=30),
        allocation=[{"label": k, "value": v, "pct": v / total} for k, v in sorted(by_type.items(), key=lambda i: -i[1])],
        totals={
            "gross": total, "net": sum(p["net"] or p["gross"] for p in products),
            "invested": invested if known else None, "gain": gain if known else None,
            "gain_pct": analytics._pct(gain, invested) if known else None,
            "next": upcoming[0] if upcoming else None, "count": len(products),
        },
    )


@app.get("/rendimentos", response_class=HTMLResponse)
def income_page(request: Request):
    book = analytics.Book()
    transactions = analytics.cash_transactions()
    credits = analytics.dividend_credits(transactions)
    yields = book.yield_by_month()
    year_ago = analytics._shift(book.today, 365)
    months: dict[str, dict[str, int]] = {}
    for c in credits:
        months.setdefault(c["d"][:7], {"prov": 0, "cdi": 0})["prov"] += c["amount"]
    for y in yields:
        months.setdefault(y["m"], {"prov": 0, "cdi": 0})["cdi"] += y["cents"]
    chart = [{"m": m, **v} for m, v in sorted(months.items())][-12:]
    first_month = analytics.month_start(11)[:7]
    prov_12m = sum(c["amount"] for c in credits if c["d"] > year_ago)
    cdi_12m = sum(y["cents"] for y in yields if y["m"] >= first_month)
    measured_12m = sum(y["cents"] for y in yields if y["m"] >= first_month and y["measured"])
    by_asset: dict[str, int] = {}
    for c in credits:
        if c["d"] > year_ago:
            label = c["ticker"] or ("Aplicação automática" if "aplic" in c["description"].lower() else "Sem ativo identificado")
            by_asset[label] = by_asset.get(label, 0) + c["amount"]
    total_assets = sum(by_asset.values())
    accounts = [
        {"name": name, "pct": s["cdi_pct"], "pct_text": f"{s['cdi_pct']:g}", "balance": s["values"][-1],
         "institution": s["institution"]}
        for name, s in book.balance_series.items() if s["type"] == "BANK"
    ]
    last_rate = book.cdi[book.cdi_dates[-1]] if book.cdi_dates else None
    per_day = sum(a["balance"] * (last_rate or 0) / 100 * a["pct"] / 100 for a in accounts if a["balance"] > 0)
    return _page(
        request, "income.html", credits=credits[:300], yields=list(reversed(yields)), chart=chart,
        accounts=accounts, checks=list(reversed(book.yield_checks))[:12],
        by_asset=[{"label": k, "value": v, "pct": v / total_assets}
                  for k, v in sorted(by_asset.items(), key=lambda i: -i[1]) if total_assets],
        kpis={
            "passive_12m": prov_12m + cdi_12m, "monthly_avg": (prov_12m + cdi_12m) // 12,
            "prov_12m": prov_12m, "cdi_12m": cdi_12m, "measured_share": analytics._pct(measured_12m, cdi_12m),
            "per_day": int(per_day), "per_month": int(per_day * 21),
            "cdi_rate": last_rate, "cdi_date": book.cdi_dates[-1] if book.cdi_dates else None,
            "cdi_annual": (1 + last_rate / 100) ** 252 - 1 if last_rate else None,
        },
    )


@app.post("/rendimentos/config")
async def save_income_config(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf_token", "")))
    saved = 0
    for key, value in form.items():
        if not key.startswith("pct:"):
            continue
        text = str(value).strip().replace("%", "").replace(",", ".")
        try:
            pct_value = float(text) if text else 0.0
        except ValueError:
            _flash(request, "error", f"Percentual inválido para {key[4:]}: {value}.")
            continue
        if not 0 <= pct_value <= 300:
            _flash(request, "error", f"{key[4:]}: use um percentual entre 0 e 300% do CDI.")
            continue
        db.set_setting("cdi_pct:" + key[4:], f"{pct_value:g}")
        saved += 1
    if saved:
        _flash(request, "success", "Percentuais do CDI salvos.")
    return _redirect(request, "/rendimentos")


@app.get("/previdencia", response_class=HTMLResponse)
def pension_page(request: Request):
    book = analytics.Book()
    return _page(
        request, "pension.html", summary=book.pension(), entries=pension.entries(), plans=pension.plans(),
        plan_types=pension.PLAN_TYPES, regimes=pension.TAX_REGIMES, today=analytics.date.today().isoformat(),
    )


@app.post("/previdencia")
async def save_pension(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf_token", "")))
    try:
        name = pension.save_entry({key: str(value) for key, value in form.items()})
        _flash(request, "success", f"Saldo de {name} registrado.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/previdencia")


@app.post("/previdencia/excluir")
def delete_pension(request: Request, csrf_token: str = Form(...), entry_id: int = Form(...)):
    _check_csrf(request, csrf_token)
    pension.delete_entry(entry_id)
    _flash(request, "success", "Lançamento excluído.")
    return _redirect(request, "/previdencia")


@app.get("/contas", response_class=HTMLResponse)
def accounts_page(request: Request):
    book = analytics.Book()
    transactions = analytics.cash_transactions()
    accounts = book.accounts()
    return _page(
        request, "accounts.html", accounts=accounts, transactions=transactions[:400],
        trends=spending.category_trends(transactions), rules=spending.rules(),
        category_overview=spending.categories_overview(transactions), deleted_categories=spending.deleted_categories(),
        category_options=spending.known_categories(),
        budget=budgets.status(transactions), budget_list=budgets.budgets(),
        budget_suggestions=budgets.suggestions(transactions), advice=budgets.latest_advice(),
        spend_categories=[c for c in spending.known_categories()
                          if c not in INTERNAL_CATEGORIES and (c not in INCOME_CATEGORIES or c in ("Outros", "Pix e transferências"))],
        chart_flow=analytics.cash_flow(transactions + book.yield_entries()),
        categories=analytics.spending_by_category(transactions, analytics.month_start(2)),
        cash=sum(a["balance"] for a in accounts if a["type"] == "BANK"),
        card_due=-sum(a["balance"] for a in accounts if a["type"] == "CREDIT"),
        has_card=any(a["type"] == "CREDIT" for a in accounts),
    )


@app.get("/contas/gastos/{category:path}", response_class=HTMLResponse)
def category_page(request: Request, category: str):
    transactions = analytics.cash_transactions()
    detail = spending.category_detail(transactions, category)
    if detail is None:
        _flash(request, "warning", f"Nenhum gasto na categoria {category}.")
        return _redirect(request, "/contas")
    budget = budgets.status(transactions)
    trends = spending.category_trends(transactions)
    return _page(
        request, "category.html", detail=detail,
        budgets=[b for b in budget["items"] if category in b["categories"] or b.get("is_total")],
        other_categories=[c["category"] for c in trends["categories"]],
        category_options=spending.known_categories(),
    )


def _local_path(back: str, fallback: str) -> str:
    return back if back.startswith("/") and not back.startswith("//") else fallback


@app.post("/orcamento")
async def save_budget(request: Request):
    form = await request.form()
    _check_csrf(request, str(form.get("csrf_token", "")))
    try:
        limit = pension.parse_amount(str(form.get("limit", "")), "o limite mensal")
        alert_text = str(form.get("alert_pct", "") or "80").replace("%", "").replace(",", ".").strip()
        budget_id = str(form.get("budget_id", "")).strip()
        categories = [str(c) for c in form.getlist("categories")]
        if str(form.get("total", "")) == "on":
            categories = [budgets.TOTAL]
        saved = budgets.save_budget(
            str(form.get("name", "")), categories, limit, float(alert_text) / 100,
            budget_id=int(budget_id) if budget_id.isdigit() else None,
        )
        _flash(request, "success", f"Meta \"{saved['name']}\" salva: {brl(limit)} por mês.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/contas#orcamento")


@app.post("/orcamento/excluir")
def delete_budget(request: Request, csrf_token: str = Form(...), budget_id: int = Form(...)):
    _check_csrf(request, csrf_token)
    budgets.delete_budget(budget_id)
    _flash(request, "success", "Meta de gasto excluída.")
    return _redirect(request, "/contas#orcamento")


@app.post("/orcamento/sugeridas")
def create_suggested_budgets(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        created = budgets.create_suggested(analytics.cash_transactions())
        _flash(request, "success", f"{created} meta(s) criada(s) pela média dos últimos 3 meses. Ajuste o que quiser.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/contas#orcamento")


@app.post("/orcamento/aplicar")
def apply_budget_advice(request: Request, csrf_token: str = Form(...), item_id: int = Form(...),
                        back: str = Form("/contas#orcamento")):
    _check_csrf(request, csrf_token)
    try:
        _flash(request, "success", budgets.apply_advice(item_id))
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, _local_path(back, "/contas"))


@app.post("/contas/categoria")
def recategorize(request: Request, csrf_token: str = Form(...), transaction_id: int = Form(...),
                 category: str = Form(""), create_rule: str = Form(""), description: str = Form(""),
                 back: str = Form("/contas#movimentacoes")):
    _check_csrf(request, csrf_token)
    try:
        spending.set_category([transaction_id], category)
        if create_rule == "on" and category.strip() and description.strip():
            rule = spending.add_rule(description.split("|")[0], category)
            _flash(request, "success", f"Regra criada: '{rule['pattern']}' → {rule['category']} ({rule['matches']} lançamento(s)).")
        else:
            _flash(request, "success", f"Categoria alterada para {category.strip() or 'automática'}.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, _local_path(back, "/contas#movimentacoes"))


@app.post("/contas/categorias")
def create_category(request: Request, csrf_token: str = Form(...), name: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        result = spending.create_category(name)
        if result["criada"]:
            _flash(request, "success", f"Categoria {result['categoria']} criada.")
        else:
            _flash(request, "warning", f"A categoria {result['categoria']} já existe.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/contas#categorias")


@app.post("/contas/categorias/excluir")
def delete_category(request: Request, csrf_token: str = Form(...), name: str = Form(...),
                    destination: str | None = Form(None)):
    _check_csrf(request, csrf_token)
    try:
        r = spending.delete_category(name, destination)
        if not r["excluida"]:
            _flash(request, "warning", f"A categoria {r['categoria']} {r['motivo']}.")
        else:
            moved = []
            if r["lancamentos"]:
                moved.append(f"{r['lancamentos']} lançamento(s)")
            if r["regras_movidas"] or r["regras_removidas"]:
                moved.append(f"{r['regras_movidas'] + r['regras_removidas']} regra(s)")
            if r["metas_ajustadas"] or r["metas_removidas"]:
                moved.append(f"{r['metas_ajustadas'] + len(r['metas_removidas'])} meta(s)")
            where = f" {', '.join(moved)} foram para {r['destino']}." if moved else ""
            _flash(request, "success", f"Categoria {r['categoria']} excluída.{where} Dá para restaurar em Categorias.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/contas#categorias")


@app.post("/contas/categorias/restaurar")
def restore_category(request: Request, csrf_token: str = Form(...), name: str = Form(...)):
    _check_csrf(request, csrf_token)
    r = spending.restore_category(name)
    if r["restaurada"]:
        _flash(request, "success", f"Categoria {r['categoria']} restaurada: {r['lancamentos']} lançamento(s), "
                                   f"{r['regras']} regra(s) e {r['metas']} meta(s) voltaram.")
    else:
        _flash(request, "warning", f"A categoria {r['categoria']} {r['motivo']}.")
    return _redirect(request, "/contas#categorias")


@app.post("/contas/regras")
def add_category_rule(request: Request, csrf_token: str = Form(...), pattern: str = Form(...),
                      category: str = Form(...), account_name: str = Form("")):
    _check_csrf(request, csrf_token)
    try:
        rule = spending.add_rule(pattern, category, account_name or None)
        _flash(request, "success", f"Regra '{rule['pattern']}' → {rule['category']}: {rule['matches']} lançamento(s) afetado(s).")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request, "/contas#regras")


@app.post("/contas/regras/excluir")
def delete_category_rule(request: Request, csrf_token: str = Form(...), rule_id: int = Form(...)):
    _check_csrf(request, csrf_token)
    spending.delete_rule(rule_id)
    _flash(request, "success", "Regra excluída.")
    return _redirect(request, "/contas#regras")


@app.get("/conciliacao", response_class=HTMLResponse)
def reconciliation_page(request: Request):
    transactions = analytics.cash_transactions()
    since = analytics.month_start(2)
    return _page(
        request, "reconciliation.html",
        transfer_pairs=[t for t in transactions if t.get("transfer_with") and t["amount_cents"] < 0 and t["transaction_date"] >= since],
        transfer_orphans=analytics.unmatched_transfers(transactions, since),
        position_alerts=db.rows("SELECT * FROM v_position_reconciliation WHERE status <> 'OK' ORDER BY status, ticker"),
        bank_alerts=db.rows("SELECT * FROM v_bank_balance_reconciliation WHERE status <> 'OK' ORDER BY status, account_name"),
        reconciliation_notes=db.rows("SELECT * FROM reconciliation_note WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 50"),
        recent_runs=db.rows("SELECT * FROM sync_run ORDER BY id DESC LIMIT 15"),
        database_path=db.database_path(),
    )


@app.get("/configuracoes", response_class=HTMLResponse)
def settings_page(request: Request):
    return _page(
        request, "settings.html",
        pluggy_client_id_status=_secret_configured("pluggy_client_id"),
        pluggy_client_secret_status=_secret_configured("pluggy_client_secret"),
        brapi_token_status=_secret_configured("brapi_token"),
        item_ids=", ".join(pluggy_item_ids()),
        pluggy_accounts=db.rows(
            "SELECT institution, account_name, account_type, external_key FROM financial_account "
            "WHERE provider = 'pluggy' ORDER BY institution, account_type, account_name"
        ),
        daily_quotes_enabled=db.get_setting("daily_quotes_enabled", "1") == "1",
        display_name=db.get_setting("display_name"),
    )


@app.get("/importar", response_class=HTMLResponse)
def imports_page(request: Request):
    return _page(request, "imports.html", recent_runs=db.rows("SELECT * FROM sync_run ORDER BY id DESC LIMIT 8"))


@app.get("/importacoes")
def imports_legacy():
    return RedirectResponse("/importar", status_code=301)


@app.post("/configuracoes")
def save_settings(
    request: Request,
    csrf_token: str = Form(...),
    pluggy_client_id: str = Form(""),
    pluggy_client_secret: str = Form(""),
    pluggy_item_ids: str = Form(""),
    brapi_token: str = Form(""),
    daily_quotes: str = Form(""),
    display_name: str = Form(""),
    remove_pluggy: str = Form(""),
    remove_brapi: str = Form(""),
):
    _check_csrf(request, csrf_token)
    try:
        if pluggy_client_id.strip():
            save_secret("pluggy_client_id", pluggy_client_id.strip())
        if pluggy_client_secret.strip():
            save_secret("pluggy_client_secret", pluggy_client_secret.strip())
        if brapi_token.strip():
            save_secret("brapi_token", brapi_token.strip())
        if remove_pluggy == "on":
            delete_secret("pluggy_client_id")
            delete_secret("pluggy_client_secret")
        if remove_brapi == "on":
            delete_secret("brapi_token")
    except Exception:
        _flash(request, "error", "Não foi possível acessar o cofre seguro do Windows. Revise as configurações e tente novamente.")
        return _redirect(request, "/configuracoes")
    item_ids, ignored = parse_item_ids(pluggy_item_ids)
    db.set_setting("pluggy_item_ids", ", ".join(item_ids))
    if ignored:
        _flash(request, "warning", "Ignorado por não ser um Item ID válido: " + ", ".join(ignored[:5]) + ".")
    db.set_setting("daily_quotes_enabled", "1" if daily_quotes == "on" else "0")
    db.set_setting("display_name", " ".join(display_name.split())[:40])
    _flash(request, "success", "Configurações salvas. Segredos ficam no Credential Manager do Windows.")
    return _redirect(request, "/configuracoes")


def _read_upload(file: UploadFile, max_bytes: int = 10 * 1024 * 1024) -> bytes:
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"O arquivo excede o limite local de {max_bytes // (1024 * 1024)} MB.")
    return content


@app.post("/importar")
def upload_any(request: Request, csrf_token: str = Form(...), files: list[UploadFile] = File(...)):
    _check_csrf(request, csrf_token)
    for upload in files[:20]:
        name = upload.filename or "arquivo"
        try:
            result = import_file(name, _read_upload(upload, 25 * 1024 * 1024))
            _flash(request, "success", f"{name} · {result.kind} · {result.message}")
        except ValueError as exc:
            _flash(request, "error", f"{name} · {exc}")
        except Exception:
            _flash(request, "error", f"{name} · falha inesperada; nada foi gravado deste arquivo.")
    return _redirect(request, "/importar")


@app.post("/importar/ofx")
def upload_ofx(request: Request, csrf_token: str = Form(...), file: UploadFile = File(...)):
    _check_csrf(request, csrf_token)
    if Path(file.filename or "").suffix.lower() not in {".ofx", ".qfx", ".ofc"}:
        _flash(request, "error", "Envie um extrato OFX/QFX exportado pelo Nubank.")
        return _redirect(request, "/importar")
    try:
        count = import_ofx(_read_upload(file))
        _flash(request, "success", f"Extrato importado. {count} movimentação(ões) processada(s); reimportar não duplica registros.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Falha ao importar o OFX; a base anterior foi preservada.")
    return _redirect(request, "/importar")


@app.post("/importar/posicoes")
def upload_positions(request: Request, csrf_token: str = Form(...), file: UploadFile = File(...)):
    _check_csrf(request, csrf_token)
    try:
        count = import_positions_csv(_read_upload(file))
        _flash(request, "success", f"{count} posição(ões) importada(s). Quantidades são mantidas em milionésimos.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Falha ao importar posições; a base anterior foi preservada.")
    return _redirect(request, "/importar")


@app.post("/importar/cotacoes")
def upload_quotes(request: Request, csrf_token: str = Form(...), file: UploadFile = File(...)):
    _check_csrf(request, csrf_token)
    try:
        count = import_quotes_csv(_read_upload(file))
        _flash(request, "success", f"{count} fechamento(s) importado(s) no SQLite.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Falha ao importar cotações; a base anterior foi preservada.")
    return _redirect(request, "/importar")


@app.post("/sincronizar/pluggy")
def pluggy_sync(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        result = sync_pluggy()
        kind = "warning" if result["status"] == "partial" else "success"
        _flash(request, kind, result["message"])
    except SyncError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request)


@app.post("/sincronizar/cotacoes")
def quote_sync(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        result = sync_daily_quotes()
        kind = "error" if result["status"] == "failed" else "warning" if result["status"] == "partial" else "success"
        _flash(request, kind, result["message"])
    except SyncError as exc:
        _flash(request, "error", str(exc))
    return _redirect(request)


@app.post("/conciliacao/nota")
def add_reconciliation_note(
    request: Request,
    csrf_token: str = Form(...),
    entity_type: str = Form(...),
    entity_key: str = Form(...),
    note: str = Form(...),
):
    _check_csrf(request, csrf_token)
    normalized_type = entity_type.strip().lower()
    normalized_key = entity_key.strip()
    normalized_note = note.strip()
    if (
        normalized_type not in {"position", "bank"}
        or not normalized_key
        or len(normalized_key) > 250
        or not normalized_note
        or len(normalized_note) > 1000
    ):
        _flash(request, "error", "Informe uma pendência e uma observação válida.")
        return _redirect(request, "/conciliacao")
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO reconciliation_note(entity_type, entity_key, note) VALUES (?, ?, ?)",
            (normalized_type, normalized_key, normalized_note),
        )
    _flash(request, "success", "Observação registrada.")
    return _redirect(request, "/conciliacao")


@app.post("/conciliacao/resolver")
def resolve_reconciliation_note(
    request: Request,
    csrf_token: str = Form(...),
    note_id: int = Form(...),
):
    _check_csrf(request, csrf_token)
    with db.transaction() as connection:
        updated = connection.execute(
            "UPDATE reconciliation_note SET resolved_at = CURRENT_TIMESTAMP WHERE id = ? AND resolved_at IS NULL",
            (note_id,),
        ).rowcount
    if updated:
        _flash(request, "success", "Observação marcada como resolvida.")
    else:
        _flash(request, "warning", "A observação já foi resolvida ou não foi encontrada.")
    return _redirect(request, "/conciliacao")


@app.get("/csv/modelo-posicoes.csv")
def positions_template():
    return Response(
        "ticker;quantity;as_of_date;average_price;account_name;asset_class;currency\r\n"
        "PETR4;100;2026-01-02;32,50;Nubank / NuInvest;Ação;BRL\r\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modelo-posicoes.csv"'},
    )


@app.get("/csv/modelo-cotacoes.csv")
def quotes_template():
    return Response(
        "ticker;trade_date;close;asset_class\r\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modelo-cotacoes.csv"'},
    )


@app.get("/csv/modelo-operacoes.csv")
def operations_template():
    return Response(
        "date;ticker;type;quantity;price;fees;account_name\r\n"
        "2026-01-02;ITSA4;BUY;100;10,25;0;Nubank / NuInvest\r\n"
        "2026-02-15;ITSA4;DIVIDEND;100;0,05;0;Nubank / NuInvest\r\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modelo-operacoes.csv"'},
    )


@app.get("/csv/modelo-renda-fixa.csv")
def fixed_income_template():
    return Response(
        "name;type;as_of_date;gross_value;invested;net_value;issuer;indexer;rate;maturity;account_name\r\n"
        "Caixinha Reserva;Caixinha;2026-09-22;5230,10;5000;5190,00;Nubank;CDI;100%;;Nubank\r\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modelo-renda-fixa.csv"'},
    )


@app.post("/backup")
def download_backup(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    path = db.create_backup()
    return FileResponse(path, filename=path.name, media_type="application/vnd.sqlite3")


@app.post("/restaurar")
def restore_backup(
    request: Request,
    csrf_token: str = Form(...),
    confirmed: str = Form(""),
    file: UploadFile = File(...),
):
    _check_csrf(request, csrf_token)
    if confirmed != "on":
        _flash(request, "error", "Marque a confirmação para substituir os dados atuais por um backup.")
        return _redirect(request, "/importar")
    try:
        previous = db.restore_database(_read_upload(file, 250 * 1024 * 1024))
        _flash(request, "success", f"Backup restaurado. Cópia preventiva salva em {previous}.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Não foi possível restaurar o arquivo; os dados atuais foram preservados.")
    return _redirect(request)
