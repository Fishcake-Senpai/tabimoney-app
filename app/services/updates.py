"""Aviso de versão nova: consulta o último Release público do GitHub e compara com a versão instalada.

A consulta sai no máximo a cada 12 horas (e ao abrir o app), não manda nenhum dado do usuário e pode ser
desligada em Configurações. Sem internet, o aviso simplesmente não aparece.
"""
from __future__ import annotations

import json
import logging
import platform
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import __version__
from app.db import get_setting, set_setting

REPO = "Fishcake-Senpai/tabimoney-app"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INTERVAL = timedelta(hours=12)

KEY_ENABLED = "update_check_enabled"
KEY_LATEST = "update_latest"
KEY_CHECKED = "update_checked_at"
KEY_ERROR = "update_error"
KEY_DISMISSED = "update_dismissed"

log = logging.getLogger("tabimoney.updates")
_lock = threading.Lock()


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(n) for n in match.groups()) if match else None  # type: ignore[return-value]


def _rosetta() -> bool:
    """Build Intel rodando num Mac com chip Apple (Rosetta): o zip certo é o de Apple Silicon."""
    try:
        out = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def platform_suffix() -> str | None:
    """Sufixo do zip deste computador no Release (…-windows.zip, …-mac-apple-silicon.zip, …-mac-intel.zip)."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac-apple-silicon" if platform.machine() == "arm64" or _rosetta() else "mac-intel"
    return None


def enabled() -> bool:
    return get_setting(KEY_ENABLED, "1") == "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check(force: bool = False) -> dict[str, Any]:
    """Consulta o GitHub se estiver ligado e a última consulta tiver mais de 12 h (ou se force=True).
    Devolve o resultado guardado: {'version', 'url', 'download_url', 'published_at'} ou {}."""
    with _lock:
        if not force:
            if not enabled():
                return latest()
            checked = get_setting(KEY_CHECKED)
            if checked and _now() - datetime.fromisoformat(checked) < INTERVAL:
                return latest()
        try:
            response = httpx.get(
                LATEST_URL, timeout=10, follow_redirects=True,
                headers={"Accept": "application/vnd.github+json", "User-Agent": f"Tabimoney/{__version__}"},
            )
            if response.status_code == 404:  # nenhum Release publicado ainda
                data: dict[str, Any] = {}
            else:
                response.raise_for_status()
                release = response.json()
                suffix = platform_suffix()
                asset = next((a for a in release.get("assets", [])
                              if suffix and a.get("name", "").endswith(f"-{suffix}.zip")), None)
                data = {
                    "version": str(release.get("tag_name", "")).lstrip("v"),
                    "url": release.get("html_url") or RELEASES_URL,
                    "download_url": asset.get("browser_download_url") if asset else None,
                    "published_at": release.get("published_at"),
                }
            set_setting(KEY_LATEST, json.dumps(data))
            set_setting(KEY_ERROR, "")
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Não foi possível verificar versão nova: %s", exc)
            set_setting(KEY_ERROR, "Sem resposta do GitHub (sem internet?)")
        set_setting(KEY_CHECKED, _now().isoformat(timespec="seconds"))
        return latest()


def latest() -> dict[str, Any]:
    try:
        return json.loads(get_setting(KEY_LATEST) or "{}")
    except ValueError:
        return {}


def status() -> dict[str, Any] | None:
    """O aviso a mostrar no topo das páginas, ou None (desligado, em dia ou dispensado)."""
    if not enabled():
        return None
    info = latest()
    newest, current = parse_version(info.get("version")), parse_version(__version__)
    if not newest or not current or newest <= current or info.get("version") == get_setting(KEY_DISMISSED):
        return None
    return {**info, "current": __version__, "frozen": getattr(sys, "frozen", False)}


def summary() -> dict[str, Any]:
    """Para a tela de Configurações."""
    info = latest()
    newest, current = parse_version(info.get("version")), parse_version(__version__)
    return {
        "enabled": enabled(), "current": __version__, "latest": info.get("version"), "url": info.get("url"),
        "checked_at": get_setting(KEY_CHECKED), "error": get_setting(KEY_ERROR),
        "outdated": bool(newest and current and newest > current),
    }


def dismiss(version: str) -> None:
    set_setting(KEY_DISMISSED, version)


def set_enabled(value: bool) -> None:
    set_setting(KEY_ENABLED, "1" if value else "0")


def scheduler(stop_event: threading.Event) -> None:
    """Verifica logo depois de abrir (dá tempo do app subir) e depois a cada meia hora; check() respeita as 12 h."""
    if stop_event.wait(5):
        return
    while True:
        try:
            check()
        except Exception:  # noqa: BLE001 - o aviso nunca pode derrubar o app
            log.exception("Falha inesperada ao verificar versão nova")
        if stop_event.wait(1800):
            return
