"""Sobe o Tabimoney de verdade para os testes de navegador, sem tocar nos dados nem no cofre do usuário.

    python tests/e2e/servidor.py PASTA

Usa a PASTA como pasta de dados (base nova), um cofre de senhas em memória e nenhuma rede. Grava na base
principal os mesmos dados da demonstração (app/demo.py: Lucas e Marina), para os testes cobrirem todas as telas
com dados, e escuta em 127.0.0.1 na porta de TABIMONEY_PORTA (padrão 8765), a única que o app então aceita.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def isolar(pasta: Path) -> None:
    home = pasta / "home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "LOCALAPPDATA": str(pasta / "localappdata"), "XDG_DATA_HOME": str(pasta / "xdg"),
        "USERPROFILE": str(home), "HOME": str(home),
    })
    Path.home = classmethod(lambda cls: home)  # Mac guarda a base em ~/Library

    import httpx

    from app import security
    from tests.conftest import CofreFalso

    cofre = CofreFalso()
    security._system_vault = lambda: cofre

    def sem_rede(*_args, **_kwargs):
        raise httpx.ConnectError("rede desligada nos testes de navegador")

    httpx.get = httpx.post = sem_rede
    httpx.Client.send = sem_rede


def semear() -> None:
    from app import db, demo

    db.init_db()
    demo.seed()


def main() -> None:
    pasta = Path(sys.argv[1]).resolve()
    isolar(pasta)
    semear()

    import uvicorn

    from app import main as app_main

    app_main.quote_scheduler = lambda _stop: None
    app_main.updates.scheduler = lambda _stop: None
    uvicorn.run(app_main.app, host="127.0.0.1", port=app_main.PORT, log_level="warning")


if __name__ == "__main__":
    main()
