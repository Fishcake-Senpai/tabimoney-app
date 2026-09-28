"""Sobe o Tabimoney de verdade para os testes de navegador, sem tocar nos dados nem no cofre do usuário.

    python tests/e2e/servidor.py PASTA

Usa a PASTA como pasta de dados (base nova), um cofre de senhas em memória e nenhuma rede. Grava os dados de
exemplo dos testes e um casal (Gabriel e Ana, cada um com Nubank e ITSA4), e escuta em 127.0.0.1:8765, a única
porta que o app aceita.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
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
    from app import db
    from app.services import household
    from tests.conftest import semear_exemplo

    db.init_db()
    hoje = semear_exemplo()
    household.update_member(1, "Gabriel")
    ana = household.add_member("Ana")["id"]
    ontem = (hoje - timedelta(days=1)).isoformat()
    with db.transaction() as con:
        con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key, "
                    "member_id) VALUES (10, 'Nubank', 'Nubank ••••0009 · Ana', 'BANK', 'pluggy', 'item:ana:account:1', ?)",
                    (ana,))
        con.execute("INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
                    "VALUES (10, 'pluggy', ?, 420000)", (hoje.isoformat(),))
        con.execute("INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
                    "amount_cents, category) VALUES (10, 'pluggy', 'ana1', ?, 'Farmácia da Ana', -4500, 'Saúde')", (ontem,))
        for conta, nome, titular in ((20, "Nubank / NuInvest", None), (21, "Nubank / NuInvest · Ana", ana)):
            con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, "
                        "external_key, member_id) VALUES (?, 'Nubank', ?, 'INVESTMENT', 'pluggy', ?, ?)",
                        (conta, nome, f"item:{conta}:investments", titular))
        con.execute("INSERT INTO instrument(id, ticker, name, asset_class) VALUES (1, 'ITSA4', 'Itaúsa', 'Ação')")
        for conta, quantidade in ((20, 100), (21, 40)):
            con.execute("INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
                        "VALUES (?, 1, 'pluggy', ?, ?)", (conta, (hoje - timedelta(days=30)).isoformat(), quantidade * 1_000_000))
        for dias in range(40, -1, -1):
            dia = hoje - timedelta(days=dias)
            if dia.weekday() < 5:
                con.execute("INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
                            "VALUES (1, ?, ?, 'brapi')", (dia.isoformat(), 1000 + dias))


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
