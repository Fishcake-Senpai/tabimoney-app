"""Testes de navegador: o app de verdade (tests/e2e/servidor.py) num Chromium controlado pelo Playwright.

Rodar: pip install -r requirements-e2e.txt, python -m playwright install chromium e python -m pytest tests/e2e.
O Tabimoney do dia a dia precisa estar fechado: o app só aceita a porta 8765.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ENDERECO = "http://127.0.0.1:8765"


def _porta_aberta() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", 8765)) == 0


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    """Sobe o servidor de teste uma vez para a sessão; o Playwright resolve page.goto("/contas") a partir daqui."""
    if _porta_aberta():
        # No CI é erro; na máquina de quem desenvolve, o Tabimoney aberto só adia estes testes.
        (pytest.fail if os.environ.get("CI") else pytest.skip)(
            "A porta 8765 está em uso. Feche o Tabimoney para rodar os testes de navegador."
        )
    pasta = tmp_path_factory.mktemp("e2e")
    log = (pasta / "servidor.log").open("w", encoding="utf-8")
    processo = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("servidor.py")), str(pasta)], stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(120):
            if processo.poll() is not None or _porta_aberta():
                break
            time.sleep(0.25)
        if not _porta_aberta():
            log.flush()
            pytest.fail("O servidor de teste não subiu:\n" + (pasta / "servidor.log").read_text(encoding="utf-8")[-3000:])
        yield ENDERECO
    finally:
        processo.terminate()
        try:
            processo.wait(timeout=10)
        except subprocess.TimeoutExpired:
            processo.kill()
        log.close()


@pytest.fixture
def erros_js(page):
    """Erros de JavaScript e do console. Todo teste de tela confere que a lista termina vazia."""
    erros: list[str] = []
    page.on("pageerror", lambda exc: erros.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: erros.append(f"console: {msg.text}") if msg.type == "error" else None)
    return erros


@pytest.fixture(autouse=True)
def sem_erros_js(request):
    if "page" not in request.fixturenames:
        yield
        return
    erros = request.getfixturevalue("erros_js")
    yield
    assert not erros, "\n".join(erros)


@pytest.fixture
def aceitar_confirmacoes(page):
    """Os botões com data-confirm abrem um confirm(); o Playwright recusa por padrão."""
    page.on("dialog", lambda dialog: dialog.accept())
    return page
