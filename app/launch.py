"""Ponto de entrada do Tabimoney (run.bat/run.command, Tabimoney.exe no Windows e Tabimoney.app no Mac).
No Mac, o executável fica em Tabimoney.app/Contents/MacOS/Tabimoney e aceita os mesmos argumentos.

    Tabimoney.exe                 abre o app: encerra o que já estava aberto, sobe o servidor em segundo plano
                                  e abre o navegador. A janela mostra o progresso e fecha sozinha.
    Tabimoney.exe cli <comando>   a linha de comando (financas.bat), para você e para agentes de IA.
    Tabimoney.exe --servidor      o servidor em si (o passo anterior chama este, sem janela).
    Tabimoney.exe --primeiro-plano servidor nesta janela, com o log na tela (para investigar problemas).

Clicar de novo reinicia: o servidor aberto recebe um pedido de encerramento autenticado por um token guardado
no arquivo de trava, termina o que estiver fazendo e sai; se não responder, o processo é finalizado.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import __version__
from app.db import data_dir

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
FROZEN = getattr(sys, "frozen", False)


def lock_path() -> Path:
    return data_dir() / "tabimoney.lock"


def log_path() -> Path:
    folder = data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "tabimoney.log"


def _read_lock() -> dict | None:
    try:
        return json.loads(lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def _wait(condition, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.25)
    return condition()


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    import signal

    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 0)):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        if _wait(lambda: not _pid_alive(pid), grace):
            return


def stop_previous(say=print) -> None:
    """Encerra o Tabimoney que estiver aberto. Levanta RuntimeError se a porta estiver com outro programa."""
    info = _read_lock()
    pid = int(info.get("pid", 0)) if info else 0
    alive = bool(pid) and _pid_alive(pid)
    if not alive and not _port_open():
        return
    if info and alive:
        version = info.get("version", "?")
        say(f"Reiniciando o Tabimoney que já estava aberto (versão {version})…")
        try:
            import httpx

            httpx.post(f"{URL}/_sistema/encerrar", headers={"X-Tabimoney-Token": info.get("token", "")}, timeout=5)
        except Exception:  # noqa: BLE001 - se não respondeu, o processo é finalizado abaixo
            pass
        if not _wait(lambda: not _pid_alive(pid) and not _port_open(), 15):
            say("O app aberto não respondeu; finalizando o processo…")
            _kill(pid)
            _wait(lambda: not _port_open(), 10)
    if _port_open():
        raise RuntimeError(
            f"A porta {PORT} está ocupada por outro programa (ou por um Tabimoney antigo aberto pelo terminal). "
            "Feche o outro Tabimoney, ou reinicie o computador, e abra de novo."
        )


# ---------------------------------------------------------------- servidor

def _setup_file_logging() -> None:
    handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    stream = open(log_path().with_suffix(".stderr.log"), "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = stream


def run_server(foreground: bool = False) -> None:
    import uvicorn

    if not foreground:
        _setup_file_logging()
    from app.main import app

    token = secrets.token_urlsafe(32)
    config = uvicorn.Config(app, host=HOST, port=PORT, workers=1, access_log=False,
                            log_config=None if not foreground else uvicorn.config.LOGGING_CONFIG)
    server = uvicorn.Server(config)
    app.state.server = server
    app.state.shutdown_token = token
    lock_path().write_text(json.dumps({
        "pid": os.getpid(), "token": token, "version": __version__, "exe": sys.executable,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }), encoding="utf-8")
    logging.getLogger("tabimoney").info("Tabimoney %s iniciando (pid %s)", __version__, os.getpid())
    try:
        server.run()
    finally:
        info = _read_lock()
        if info and info.get("pid") == os.getpid():
            lock_path().unlink(missing_ok=True)
        logging.getLogger("tabimoney").info("Tabimoney encerrado")


# ---------------------------------------------------------------- abrir (duplo clique)

def _server_command() -> list[str]:
    if FROZEN:
        return [sys.executable, "--servidor"]
    return [sys.executable, "-m", "app.launch", "--servidor"]


def _has_console() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def _alert(message: str) -> None:
    """No Mac o Tabimoney.app abre sem terminal: o erro vira uma caixa de diálogo, senão ninguém vê."""
    if sys.platform != "darwin" or _has_console():
        return
    text = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display dialog "{text}" with title "Tabimoney" buttons {{"OK"}} default button "OK" with icon caution'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _pause_and_exit(code: int) -> None:
    if _has_console():
        try:
            input("\nPressione Enter para fechar esta janela.")
        except EOFError:
            pass
    raise SystemExit(code)


def open_app() -> None:
    print(f"Tabimoney {__version__} · finanças sérias (mais ou menos)\n")
    if FROZEN:
        from app import agent_workspace

        try:
            folder = agent_workspace.sync(Path(sys.executable))
            print(f"Pasta para a IA atualizada: {folder}")
        except OSError as exc:
            print(f"Aviso: não foi possível atualizar a pasta para a IA ({exc}).")
    try:
        stop_previous()
        print("Iniciando…")
        # o servidor precisa sobreviver a esta janela: sem console no Windows, sessão própria no Mac/Linux
        options: dict = {"start_new_session": True}
        if os.name == "nt":
            options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        root = Path(__file__).resolve().parent.parent
        # No exe de arquivo único, um filho reaproveitaria a pasta extraída desta janela, que é apagada quando
        # ela fecha. Com a variável abaixo (PyInstaller 6.9+), o servidor extrai a própria cópia e fica independente.
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        process = subprocess.Popen(
            _server_command(), cwd=None if FROZEN else root, env=env, close_fds=True, **options,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait(lambda: _port_open() or process.poll() is not None, 90) or not _port_open():
            raise RuntimeError(f"O servidor não iniciou. Veja o registro em {log_path()}")
    except RuntimeError as exc:
        print(f"\nNão deu para abrir o Tabimoney: {exc}")
        _alert(f"Não deu para abrir o Tabimoney: {exc}")
        _pause_and_exit(1)
    webbrowser.open(URL, new=2)
    print(f"\nPronto! O Tabimoney está aberto no navegador: {URL}")
    print("Esta janela fecha sozinha. Para reiniciar ou atualizar, abra o Tabimoney de novo.")
    if _has_console():
        time.sleep(4)


def main(argv: list[str] | None = None) -> None:
    # app sem terminal (Tabimoney.app aberto pelo Finder) pode vir sem stdout/stderr
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = sys.stdout
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "cli":
        from app import cli

        cli.main(args[1:])
    elif args and args[0] == "--servidor":
        run_server()
    elif args and args[0] == "--primeiro-plano":
        stop_previous()
        threading.Timer(1.5, lambda: webbrowser.open(URL, new=2)).start()
        run_server(foreground=True)
    elif args and args[0] in {"--versao", "--version"}:
        print(__version__)
    else:
        open_app()


if __name__ == "__main__":
    main()
