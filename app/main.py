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
from app.services.formatting import brl, quantity
from app.services.importers import import_ofx, import_positions_csv, import_quotes_csv
from app.services.sync import SyncError, quote_scheduler, sync_daily_quotes, sync_pluggy

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
            if origin and origin not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}:
                return PlainTextResponse("Origem não permitida.", status_code=403)
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return PlainTextResponse("Origem não permitida.", status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
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


app = FastAPI(title="Finanças Pessoais", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
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
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["brl"] = brl
templates.env.filters["quantity"] = quantity


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
    request.session["flash_messages"] = messages[-3:]


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


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    assets = db.rows("SELECT * FROM v_asset_valuation ORDER BY market_value_cents DESC, ticker")
    totals = db.rows("SELECT * FROM v_personal_totals")[0]
    bank_balances = db.rows("SELECT account_name, as_of_date, balance_cents, data_source FROM v_bank_latest_balances ORDER BY account_name")
    position_alerts = db.rows("SELECT * FROM v_position_reconciliation WHERE status <> 'OK' ORDER BY status, ticker")
    bank_alerts = db.rows("SELECT * FROM v_bank_balance_reconciliation WHERE status <> 'OK' ORDER BY status, account_name")
    recent_runs = db.rows("SELECT * FROM sync_run ORDER BY id DESC LIMIT 6")
    reconciliation_notes = db.rows(
        "SELECT * FROM reconciliation_note WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 20"
    )
    return _render(
        request, "dashboard.html", assets=assets, totals=totals,
        bank_balances=bank_balances, position_alerts=position_alerts,
        bank_alerts=bank_alerts, recent_runs=recent_runs,
        reconciliation_notes=reconciliation_notes,
        database_path=db.database_path(),
    )


@app.get("/configuracoes", response_class=HTMLResponse)
def settings_page(request: Request):
    return _render(
        request, "settings.html",
        pluggy_client_id_status=_secret_configured("pluggy_client_id"),
        pluggy_client_secret_status=_secret_configured("pluggy_client_secret"),
        brapi_token_status=_secret_configured("brapi_token"),
        item_id=db.get_setting("pluggy_item_id"),
        daily_quotes_enabled=db.get_setting("daily_quotes_enabled", "1") == "1",
    )


@app.get("/importacoes", response_class=HTMLResponse)
def imports_page(request: Request):
    return _render(request, "imports.html")


@app.post("/configuracoes")
def save_settings(
    request: Request,
    csrf_token: str = Form(...),
    pluggy_client_id: str = Form(""),
    pluggy_client_secret: str = Form(""),
    pluggy_item_id: str = Form(""),
    brapi_token: str = Form(""),
    daily_quotes: str = Form(""),
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
    db.set_setting("pluggy_item_id", pluggy_item_id.strip())
    db.set_setting("daily_quotes_enabled", "1" if daily_quotes == "on" else "0")
    _flash(request, "success", "Configurações salvas. Segredos ficam no Credential Manager do Windows.")
    return _redirect(request, "/configuracoes")


def _read_upload(file: UploadFile, max_bytes: int = 10 * 1024 * 1024) -> bytes:
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"O arquivo excede o limite local de {max_bytes // (1024 * 1024)} MB.")
    return content


@app.post("/importar/ofx")
def upload_ofx(request: Request, csrf_token: str = Form(...), file: UploadFile = File(...)):
    _check_csrf(request, csrf_token)
    if Path(file.filename or "").suffix.lower() not in {".ofx", ".qfx", ".ofc"}:
        _flash(request, "error", "Envie um extrato OFX/QFX exportado pelo Nubank.")
        return _redirect(request, "/importacoes")
    try:
        count = import_ofx(_read_upload(file))
        _flash(request, "success", f"Extrato importado. {count} movimentação(ões) processada(s); reimportar não duplica registros.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Falha ao importar o OFX; a base anterior foi preservada.")
    return _redirect(request, "/importacoes")


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
    return _redirect(request, "/importacoes")


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
    return _redirect(request, "/importacoes")


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
        return _redirect(request)
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO reconciliation_note(entity_type, entity_key, note) VALUES (?, ?, ?)",
            (normalized_type, normalized_key, normalized_note),
        )
    _flash(request, "success", "Observação registrada no SQLite.")
    return _redirect(request)


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
    return _redirect(request)


@app.get("/csv/modelo-posicoes.csv")
def positions_template():
    return Response(
        "ticker;quantity;as_of_date;account_name;asset_class;currency\r\n",
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
        return _redirect(request, "/importacoes")
    try:
        previous = db.restore_database(_read_upload(file, 250 * 1024 * 1024))
        _flash(request, "success", f"Backup restaurado. Cópia preventiva salva em {previous}.")
    except ValueError as exc:
        _flash(request, "error", str(exc))
    except Exception:
        _flash(request, "error", "Não foi possível restaurar o arquivo; os dados atuais foram preservados.")
    return _redirect(request)
