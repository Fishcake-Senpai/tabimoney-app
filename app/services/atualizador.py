"""Atualização com um clique (spec: docs/superpowers/specs/2026-10-07-atualizacao-automatica.md).

O servidor aberto baixa o zip do Release, confere o SHA-256, testa o executável novo (`--versao`), faz backup da
base e troca o executável por dois renomes na mesma pasta: um .exe rodando não pode ser sobrescrito, mas pode ser
renomeado. Antes de encerrar, dispara o vigia, que é o executável ANTIGO com `--vigiar-atualizacao`: ele abre o
novo e, se o novo não subir, desfaz a troca, restaura a base e reabre o antigo. Assim a reversão roda em código que
já funcionava nesta máquina.

Contrato entre versões (§10 da spec): as flags `--versao`, `--apos-atualizacao` e `--vigiar-atualizacao`, a rota
`GET /atualizacao/estado`, o arquivo `atualizacao.json` e os nomes `<nome>.anterior/.novo/.falhou<ext>` ao lado do
executável. Campos e nomes que já existem não mudam de sentido: a versão que baixa é a antiga, a que limpa é a nova.

Por enquanto só no Windows; no Mac o aviso continua com o botão Baixar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from app import __version__, db
from app.services import updates

MARKER = "atualizacao.json"
STAGING = "atualizacoes"
EXE_NAME = "Tabimoney.exe"
MAX_BYTES = 300 * 1024 * 1024
TEST_TIMEOUT = 90       # o exe de arquivo único leva alguns segundos para se extrair antes de responder
OLD_EXIT_TIMEOUT = 30   # o servidor antigo sair depois de disparar o vigia
NEW_UP_TIMEOUT = 120    # a versão nova subir; passou disso, o vigia desfaz
STALE_AFTER = 15 * 60   # marcador "em andamento" sem mudar há mais que isso: o processo morreu no meio

IN_PROGRESS = ("baixando", "conferindo", "preparando", "trocando", "reiniciando")
FINISHED = ("concluida", "revertida", "falhou")

log = logging.getLogger("tabimoney.atualizador")
_lock = threading.Lock()
_transport: httpx.BaseTransport | None = None  # os testes trocam por um transporte simulado
_availability_cache: dict[str, tuple[float, str | None]] = {}


class UpdateError(Exception):
    """Algo impediu a atualização antes da troca: nada mudou no computador."""


# ---------------------------------------------------------------- marcador

def marker_path() -> Path:
    return db.data_dir() / MARKER


def marker() -> dict[str, Any]:
    for _ in range(5):  # no Windows, ler enquanto outro processo troca o arquivo pode falhar por um instante
        try:
            return json.loads(marker_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            time.sleep(0.1)
    return {}


def _save(**changes: Any) -> dict[str, Any]:
    data = {**marker(), **changes, "atualizado_em": _now()}
    temporary = marker_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(temporary, marker_path())
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)
    return data


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def current() -> dict[str, Any]:
    """O marcador como a página de progresso vê: um "em andamento" parado há muito vira "falhou"."""
    data = marker()
    if data.get("estado") in IN_PROGRESS:
        try:
            age = time.time() - datetime.fromisoformat(data["atualizado_em"]).timestamp()
        except (KeyError, ValueError):
            age = STALE_AFTER + 1
        if age > STALE_AFTER:
            data = {**data, "estado": "falhou", "motivo": "A atualização foi interrompida no meio."}
    return data


# ---------------------------------------------------------------- caminhos

def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable() -> Path:
    return Path(sys.executable)


def sibling(target: Path, label: str) -> Path:
    """Tabimoney.exe -> Tabimoney.anterior.exe (e, no futuro, Tabimoney.app -> Tabimoney.anterior.app)."""
    return target.with_name(f"{target.stem}.{label}{target.suffix}")


def _free_name(path: Path) -> Path:
    """O nome livre mais próximo: apaga o que sobrou de uma vez anterior ou, se estiver preso, usa -2, -3…"""
    candidate, n = path, 1
    while candidate.exists():
        try:
            candidate.unlink()
        except OSError:
            n += 1
            candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return candidate


def _rename(source: Path, destination: Path, timeout: float = 10) -> None:
    """Renomeia tentando de novo por alguns segundos: antivírus e OneDrive seguram arquivos por um instante."""
    end = time.monotonic() + timeout
    while True:
        try:
            os.rename(source, destination)
            return
        except OSError:
            if time.monotonic() >= end:
                raise
            time.sleep(0.5)


def swap(target: Path, new: Path, previous: Path) -> None:
    """Põe `new` no lugar de `target`, guardando o atual em `previous`. Se o segundo renome falhar, desfaz o
    primeiro: nunca fica sem o executável no caminho original."""
    _rename(target, previous)
    try:
        _rename(new, target)
    except OSError:
        _rename(previous, target)
        raise


def _is_temporary(path: Path) -> bool:
    """Pasta temporária (rodando de dentro do zip, por exemplo) ou app translocado pelo macOS. Compara os caminhos
    resolvidos: no Mac, /var é um link para /private/var, e a pasta temporária aparece pelos dois nomes."""
    text = str(Path(path).resolve()).lower().replace("\\", "/")
    temp = str(Path(tempfile.gettempdir()).resolve()).lower().replace("\\", "/").rstrip("/") + "/"
    return text.startswith(temp) or "/apptranslocation/" in text


def _writable(folder: Path) -> bool:
    probe = folder / ".tabimoney-teste-escrita"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- dá para atualizar com um clique?

def blocker(info: dict[str, Any]) -> str | None:
    """Por que não dá para atualizar com um clique (o aviso volta ao botão Baixar), ou None se dá."""
    if not frozen():
        return "Rodando pelo código: atualize com git pull."
    if sys.platform != "win32":
        return "No Mac, por enquanto, baixe e substitua o app à mão."
    version = info.get("version")
    if not updates.is_newer(version):
        return "Você já está na versão mais recente."
    if not info.get("download_url"):
        return "Este Release não tem o arquivo para este computador."
    last = marker()
    if last.get("estado") == "revertida" and last.get("para") == version:
        return f"A versão {version} não abriu neste computador da última vez."
    exe = executable()
    if _is_temporary(exe):
        return "Mova o Tabimoney.exe para uma pasta sua (por exemplo, Documentos) e abra de lá."
    if not _writable(exe.parent):
        return "A pasta do Tabimoney não deixa gravar arquivos."
    size = int(info.get("size") or 0)
    if size:
        for folder in {exe.parent, db.data_dir()}:
            if shutil.disk_usage(folder).free < 3 * size:
                return "Falta espaço em disco para baixar a versão nova."
    return None


def availability(info: dict[str, Any]) -> dict[str, Any]:
    """Para o aviso do sino: {'auto': bool, 'motivo': str | None}. Guardado por 5 min: a página chama sempre."""
    key = str(info.get("version"))
    cached = _availability_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        reason = cached[1]
    else:
        try:
            reason = blocker(info)
        except OSError as exc:
            reason = f"Não deu para conferir a pasta do app ({exc})."
        _availability_cache.clear()
        _availability_cache[key] = (time.monotonic(), reason)
    return {"auto": reason is None, "motivo": reason}


# ---------------------------------------------------------------- download e conferência

def _allowed(url: httpx.URL | str) -> bool:
    parsed = httpx.URL(str(url))
    host = (parsed.host or "").lower()
    if updates.local_test_api() and host == "127.0.0.1":
        return True
    return parsed.scheme == "https" and (host == "github.com" or host.endswith(".githubusercontent.com"))


def _check_host(request: httpx.Request) -> None:
    if not _allowed(request.url):
        raise UpdateError(f"Endereço de download inesperado ({request.url.host}).")


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True, timeout=httpx.Timeout(30, read=60), transport=_transport,
        headers={"User-Agent": f"Tabimoney/{__version__}"}, event_hooks={"request": [_check_host]},
    )


def download(url: str, destination: Path, progress: Callable[[int, int], None] = lambda _d, _t: None) -> Path:
    with _client() as client, client.stream("GET", url) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        if total > MAX_BYTES:
            raise UpdateError("O arquivo da versão nova é maior que o esperado.")
        done = 0
        with destination.open("wb") as out:
            for chunk in response.iter_bytes(1024 * 256):
                done += len(chunk)
                if done > MAX_BYTES:
                    raise UpdateError("O arquivo da versão nova é maior que o esperado.")
                out.write(chunk)
                progress(done, total)
    return destination


def expected_hash(sums: str, name: str) -> str:
    """A linha de `name` no SHA256SUMS.txt (formato do sha256sum: '<hash>  <arquivo>')."""
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and len(parts[0]) == 64:
            return parts[0].lower()
    raise UpdateError(f"O SHA256SUMS.txt do Release não tem o {name}.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(archive: Path, folder: Path) -> Path:
    """Tira do zip só o executável (pelo nome exato, então não há caminho a escapar da pasta)."""
    try:
        with zipfile.ZipFile(archive) as zipped:
            try:
                member = zipped.getinfo(EXE_NAME)
            except KeyError:
                raise UpdateError(f"O zip da versão nova não tem o {EXE_NAME}.") from None
            target = folder / EXE_NAME
            with zipped.open(member) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
    except zipfile.BadZipFile:
        raise UpdateError("O arquivo baixado não é um zip válido.") from None
    return target


def _no_window() -> dict[str, Any]:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _env() -> dict[str, str]:
    # PyInstaller 6.9+: o filho extrai a própria cópia em vez de reaproveitar a pasta do pai (ver launch.open_app)
    return dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")


def verificar_executavel(exe: Path, version: str) -> None:
    """`novo --versao` tem que responder a versão esperada: pega arquivo corrompido e antivírus que bloqueou."""
    if not exe.is_file():
        raise UpdateError("O antivírus bloqueou ou apagou o arquivo novo. Baixe manualmente.")
    try:
        out = subprocess.run([str(exe), "--versao"], capture_output=True, text=True, timeout=TEST_TIMEOUT,
                             env=_env(), stdin=subprocess.DEVNULL, **_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"O executável novo não abriu ({exc}). O antivírus pode ter bloqueado.") from None
    if out.stdout.strip() != version:
        raise UpdateError(f"O executável novo respondeu a versão {out.stdout.strip() or '?'}, não a {version}.")


def detached(command: list[str]) -> subprocess.Popen:
    """Processo que sobrevive a quem o abriu, sem janela (mesmo jeito de launch.open_app)."""
    options: dict[str, Any] = {"start_new_session": True}
    if os.name == "nt":
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return subprocess.Popen(command, env=_env(), close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)


# ---------------------------------------------------------------- o servidor antigo: baixar, conferir, trocar

def start(stop_server: Callable[[], None]) -> None:
    """Começa a atualização em segundo plano. Levanta UpdateError se não der para começar."""
    with _lock:
        if current().get("estado") in IN_PROGRESS:
            raise UpdateError("Já tem uma atualização em andamento.")
        info = updates.check(force=True)  # o Release pode ter mudado desde o aviso, e o hash precisa do sums_url
        _availability_cache.clear()
        if reason := blocker(info):
            raise UpdateError(reason)
        if not info.get("sums_url"):
            raise UpdateError("Este Release não tem o SHA256SUMS.txt para conferir o arquivo. Baixe manualmente.")
        marker_path().unlink(missing_ok=True)
        _save(estado="baixando", de=__version__, para=info["version"], progresso=0.0, motivo=None,
              iniciado_em=_now(), pid_antigo=os.getpid(), exe=str(executable()))
    threading.Thread(target=run, args=(info, stop_server), name="atualizacao", daemon=True).start()


def run(info: dict[str, Any], stop_server: Callable[[], None]) -> None:
    exe = executable()
    folder = db.data_dir() / STAGING / info["version"]
    new_beside = sibling(exe, "novo")
    previous: Path | None = None
    swapped = handed_over = False
    try:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        name = info.get("asset_name") or urlsplit(info["download_url"]).path.rsplit("/", 1)[-1]
        last = [0.0]

        def progress(done: int, total: int) -> None:
            fraction = done / total if total else 0.0
            if fraction - last[0] >= 0.01 or fraction >= 1:
                last[0] = fraction
                _save(progresso=round(fraction, 3), baixado=done, total=total)

        archive = download(info["download_url"], folder / name, progress)
        _save(estado="conferindo")
        sums = folder / updates.SUMS_NAME
        download(info["sums_url"], sums)
        if sha256(archive) != expected_hash(sums.read_text(encoding="utf-8"), name):
            raise UpdateError("O arquivo baixado não confere com o SHA256SUMS.txt do Release. Nada foi trocado.")
        new = extract(archive, folder)
        verificar_executavel(new, info["version"])

        _save(estado="preparando")
        backup = db.create_backup()
        new_beside = _free_name(new_beside)
        shutil.copy2(new, new_beside)  # na mesma pasta do atual: os renomes abaixo ficam no mesmo disco
        previous = _free_name(sibling(exe, "anterior"))
        _save(estado="trocando", backup=str(backup), anterior=str(previous))
        swap(exe, new_beside, previous)
        swapped = True

        _save(estado="reiniciando")
        detached([str(previous), "--vigiar-atualizacao"])
        handed_over = True
        log.info("Atualização para %s: executável trocado; o vigia assume", info["version"])
        stop_server()
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem na página, nunca derruba o app
        log.exception("Atualização para %s falhou", info.get("version"))
        if swapped and not handed_over and previous:  # o vigia não chegou a abrir: desfaz aqui mesmo
            try:
                swap(exe, previous, _free_name(sibling(exe, "falhou")))
            except Exception:  # noqa: BLE001
                log.exception("Não deu para desfazer a troca")
        if isinstance(exc, UpdateError):
            reason = str(exc)
        elif isinstance(exc, httpx.HTTPStatusError):
            reason = f"O GitHub respondeu com erro {exc.response.status_code} ao baixar. Tente mais tarde."
        elif isinstance(exc, httpx.HTTPError):
            reason = "A conexão caiu no meio do download."
        else:
            reason = f"Erro inesperado: {exc}"
        _save(estado="falhou", motivo=reason)
        new_beside.unlink(missing_ok=True)
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- o vigia (executável antigo)

def _setup_log() -> None:
    from logging.handlers import RotatingFileHandler

    from app.launch import log_path

    handler = RotatingFileHandler(log_path().with_name("atualizacao.log"), maxBytes=500_000, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def _same_file(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def new_is_up(state: dict[str, Any]) -> bool:
    """A versão nova está no ar: porta aberta e a trava escrita por outro processo, do executável certo."""
    from app import launch

    lock = launch._read_lock()
    return bool(
        lock and launch._port_open() and lock.get("pid") != state.get("pid_antigo")
        and lock.get("version") == state.get("para") and _same_file(lock.get("exe", ""), state["exe"])
    )


def watch() -> None:
    """Roda no executável antigo: espera o antigo sair, abre o novo e confere se ele subiu; se não, desfaz."""
    from app import launch

    _setup_log()
    state = marker()
    if state.get("estado") != "reiniciando":
        log.warning("Vigia aberto sem atualização em andamento (%s)", state.get("estado"))
        return
    exe, old_pid = Path(state["exe"]), int(state.get("pid_antigo") or 0)
    if not launch._wait(lambda: not launch._pid_alive(old_pid) and not launch._port_open(), OLD_EXIT_TIMEOUT):
        log.warning("O servidor antigo não saiu; finalizando o processo %s", old_pid)
        launch._kill(old_pid)
        launch._wait(lambda: not launch._port_open(), 10)
    log.info("Abrindo a versão %s em %s", state.get("para"), exe)
    opener = detached([str(exe), "--apos-atualizacao"])
    if launch._wait(lambda: new_is_up(state), NEW_UP_TIMEOUT):
        _save(estado="concluida")
        log.info("Versão %s no ar", state.get("para"))
        return
    revert(state, opener, f"A versão {state.get('para')} não abriu em {NEW_UP_TIMEOUT // 60} minutos.")


def revert(state: dict[str, Any], opener: subprocess.Popen | None, reason: str) -> None:
    """Encerra a versão nova, põe o executável antigo de volta, restaura a base e reabre o antigo."""
    from app import launch

    log.warning("Revertendo: %s", reason)
    lock = launch._read_lock()
    if lock and lock.get("pid") and lock.get("pid") != state.get("pid_antigo") and launch._pid_alive(int(lock["pid"])):
        launch._kill(int(lock["pid"]))
    if opener is not None and opener.poll() is None:
        launch._kill(opener.pid)
    launch._wait(lambda: not launch._port_open(), 15)
    exe, previous = Path(state["exe"]), Path(state["anterior"])
    try:
        swap(exe, previous, _free_name(sibling(exe, "falhou")))
    except OSError as exc:
        log.exception("Não deu para pôr o executável antigo de volta")
        _save(estado="falhou", motivo=f"{reason} E não deu para voltar o app antigo ({exc}): ele está em {previous}.")
        return
    try:
        if state.get("backup"):
            restore(Path(state["backup"]))
    except (OSError, sqlite3.Error) as exc:
        log.exception("Não deu para restaurar a base")
        reason += f" A base não foi restaurada ({exc}); o backup está em {state['backup']}."
    _save(estado="revertida", motivo=reason)
    detached([str(exe), "--apos-atualizacao"])


def restore(backup: Path) -> None:
    """Copia o backup por cima da base pela API do SQLite: funciona mesmo com outro processo (um agente de IA)
    com a base aberta, o que impediria trocar o arquivo no Windows."""
    source = sqlite3.connect(backup)
    target = sqlite3.connect(db.database_path(), timeout=30)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


# ---------------------------------------------------------------- a versão nova: avisar e limpar

def pending_notice() -> tuple[str, str] | None:
    """A mensagem do resultado, uma vez só, na versão em que ela faz sentido."""
    state = marker()
    if state.get("avisado") or state.get("estado") not in ("concluida", "revertida"):
        return None
    if state["estado"] == "concluida" and state.get("para") == __version__:
        _save(avisado=True)
        text = f"Tabimoney atualizado para a {__version__}. Antes da troca, seus dados ganharam um backup."
        if _ai_connected():
            text += " Se usa a IA, reinicie o agente para ele usar a versão nova."
        return "success", text
    if state["estado"] == "revertida" and state.get("de") == __version__:
        _save(avisado=True)
        return "warning", (f"{state.get('motivo') or 'A versão nova não abriu.'} Voltamos para a {__version__} e "
                           "seus dados estão como antes. Baixe a versão nova manualmente ou tente mais tarde.")
    return None


def _ai_connected() -> bool:
    try:
        from app.mcp_server import instalar

        return any(c.get("conectado") for c in instalar.situacao())
    except Exception:  # noqa: BLE001
        return False


def summary() -> str | None:
    """A última tentativa, para Configurações › Atualizações."""
    state = current()
    if not state.get("estado"):
        return None
    when = (state.get("atualizado_em") or "")[:16].replace("T", " às ")
    if state["estado"] == "concluida":
        return f"Atualizado da {state.get('de')} para a {state.get('para')} em {when}."
    if state["estado"] in ("revertida", "falhou"):
        return f"A atualização para a {state.get('para')} não deu certo ({when}): {state.get('motivo')}"
    return f"Atualizando para a {state.get('para')}…"


def cleanup() -> bool:
    """Apaga o executável anterior, o que falhou e a pasta de preparo. Devolve True quando não sobrou nada.
    Só depois de a atualização terminar: enquanto o vigia confere, ele pode precisar do anterior."""
    if current().get("estado") in IN_PROGRESS:
        return False
    clean = True
    shutil.rmtree(db.data_dir() / STAGING, ignore_errors=True)
    if (db.data_dir() / STAGING).exists():
        clean = False
    if frozen():
        exe = executable()
        for label in ("anterior", "falhou", "novo"):
            for leftover in exe.parent.glob(f"{exe.stem}.{label}*{exe.suffix}"):
                try:
                    leftover.unlink()
                except OSError:  # preso por um processo antigo (o vigia ou o servidor MCP de um agente)
                    clean = False
    return clean


def janitor(stop_event: threading.Event) -> None:
    """Tenta limpar por alguns minutos depois de abrir; o que estiver preso fica para a próxima vez."""
    for _ in range(40):
        if stop_event.wait(15):
            return
        try:
            if cleanup():
                return
        except Exception:  # noqa: BLE001 - limpeza nunca derruba o app
            log.exception("Falha ao limpar arquivos da atualização")
