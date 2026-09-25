"""Fixtures dos testes.

Todo teste roda isolado: pasta de dados temporária (nunca a base real), cofre de senhas falso (nunca o
Credential Manager nem o Porta-chaves de verdade), sem rede e sem as threads de fundo do app.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import security

# o cofre verdadeiro, guardado antes de ser trocado pelo falso (tests/test_plataforma.py testa este)
COFRE_REAL = security._system_vault


class _PasswordDeleteError(Exception):
    pass


class CofreFalso:
    """Imita a API do keyring usada por app/security.py, em memória."""

    class errors:  # noqa: N801 - mesmo nome do módulo keyring.errors
        PasswordDeleteError = _PasswordDeleteError

    def __init__(self) -> None:
        self.dados: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, name: str, value: str) -> None:
        self.dados[(service, name)] = value

    def get_password(self, service: str, name: str) -> str | None:
        return self.dados.get((service, name))

    def delete_password(self, service: str, name: str) -> None:
        if (service, name) not in self.dados:
            raise _PasswordDeleteError(name)
        del self.dados[(service, name)]


@pytest.fixture(autouse=True)
def dados_isolados(tmp_path, monkeypatch):
    """Aponta a pasta de dados de todos os sistemas para uma pasta temporária e cria a base vazia."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))  # Windows
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))           # Linux
    monkeypatch.setenv("USERPROFILE", str(home))                          # pasta da IA no Windows
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)                       # Mac (~/Library/…) e pasta da IA
    from app import db

    db.init_db()
    return tmp_path


@pytest.fixture(autouse=True)
def cofre(monkeypatch):
    falso = CofreFalso()
    monkeypatch.setattr(security, "_system_vault", lambda: falso)
    return falso


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """Nenhum teste fala com a internet; quem precisar simula a resposta."""
    import httpx

    def recusar(*_args, **_kwargs):
        raise httpx.ConnectError("rede desligada nos testes")

    monkeypatch.setattr(httpx, "get", recusar)
    monkeypatch.setattr(httpx, "post", recusar)


@pytest.fixture
def client(monkeypatch):
    """O app de verdade, sem as threads de cotações e de versão nova."""
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "quote_scheduler", lambda _stop: None)
    monkeypatch.setattr(main.updates, "scheduler", lambda _stop: None)
    with TestClient(main.app, base_url=f"http://127.0.0.1:{main.PORT}", client=("127.0.0.1", 50000)) as c:
        yield c


def csrf(client) -> str:
    page = client.get("/configuracoes").text
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def avisos(html: str) -> list[tuple[str, str]]:
    return re.findall(r'class="flash flash-(\w+)" role="status">([^<]*)<', html)


def _mes(hoje: date, meses_atras: int, dia: int) -> str:
    ano, mes = hoje.year, hoje.month - meses_atras
    while mes <= 0:
        ano, mes = ano - 1, mes + 12
    return date(ano, mes, min(dia, 28)).isoformat()


@pytest.fixture
def dados_exemplo():
    """Conta, cartão e 7 meses de lançamentos variados (compras, salário, fatura, estorno, dólar, pendentes)."""
    from app import db

    hoje = date.today()
    with db.transaction() as con:
        con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
                    "VALUES (1, 'Nubank', 'Nubank ••••0001', 'BANK', 'pluggy', 'item:t:account:1')")
        con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
                    "VALUES (2, 'Nubank', 'Nubank Cartão ••••0002', 'CREDIT', 'pluggy', 'item:t:account:2')")
        con.execute("INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
                    "VALUES (1, 'pluggy', ?, 1250000)", (hoje.isoformat(),))
        con.execute("INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
                    "VALUES (2, 'pluggy', ?, -180000)", (hoje.isoformat(),))
        n = 0

        def lanc(conta, dia, descricao, centavos, categoria, status="POSTED", moeda=None, original=None):
            nonlocal n
            n += 1
            con.execute(
                "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
                "amount_cents, status, category, original_currency, original_amount_cents) "
                "VALUES (?, 'pluggy', ?, ?, ?, ?, ?, ?, ?, ?)",
                (conta, f"t{n}", dia, descricao, centavos, status, categoria, moeda, original),
            )

        for m in range(1, 7):
            lanc(1, _mes(hoje, m, 5), "Salário Empresa", 800000, "Salário")
            lanc(2, _mes(hoje, m, 6), "iFood", -4590 - m * 100, "Alimentação")
            lanc(2, _mes(hoje, m, 13), "iFood", -3890, "Alimentação")
            lanc(2, _mes(hoje, m, 9), "Supermercado Bom Preço", -32000, "Mercado")
            lanc(2, _mes(hoje, m, 17), "Anthropic* Claude Sub", -11400, "Assinaturas", moeda="USD", original=-2100)
            lanc(1, _mes(hoje, m, 10), "Pagamento de fatura", -150000, "Pagamento de fatura")
            lanc(2, _mes(hoje, m, 10), "Pagamento recebido", 150000, "Pagamento de fatura")
            lanc(1, _mes(hoje, m, 20), "Pix enviado|Maria", -20000, "Pix e transferências")
        lanc(2, _mes(hoje, 2, 21), "Estorno iFood", 3890, "Alimentação")
        lanc(1, _mes(hoje, 3, 15), "Uber", -2500, "Transporte")
        lanc(2, hoje.isoformat(), "iFood", -5000, "Alimentação", status="PENDING")          # fatura aberta: entra
        lanc(2, (hoje + timedelta(days=40)).isoformat(), "Loja 2/5", -9900, "Compras", status="PENDING")  # parcela futura
        lanc(1, hoje.isoformat(), "Pix pendente", -777, "Pix e transferências", status="PENDING")  # conta: fica fora
    return hoje
