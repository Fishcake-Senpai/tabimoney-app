"""O servidor MCP de verdade, num processo à parte, falando por stdio, como o Claude Desktop ou o Claude Code
abrem. Se qualquer coisa escrever na saída padrão fora do protocolo, a conversa quebra e o teste falha.

A pasta de dados é a temporária do conftest (as variáveis de ambiente passam para o processo filho).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from app import security

from .conftest import rodar_async

ROOT = Path(__file__).resolve().parent.parent
SITE = """\
import os

from app import security


class Vault:
    def __init__(self):
        self.data = {("FinancasPessoaisLocal", "database_key_v1"): os.environ["TABIMONEY_TEST_DB_KEY"]}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)

    class errors:
        class PasswordDeleteError(Exception):
            pass


security._system_vault = lambda: Vault()
"""


@pytest.mark.parametrize("args", [["-m", "app.mcp_server", "--demo"], ["-m", "app.launch", "mcp", "--demo"]],
                         ids=["python -m app.mcp_server", "Tabimoney mcp"])
def test_servidor_por_stdio(args, tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(SITE, encoding="utf-8")
    key = security.get_secret("database_key_v1")
    env = {
        **os.environ,
        "PYTHONPATH": f"{site}{os.pathsep}{ROOT}",
        "PYTHONIOENCODING": "utf-8",
        "TABIMONEY_TEST_DB_KEY": key,
    }
    params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=str(ROOT))

    async def conversa():
        async with Client(params, mode="legacy", read_timeout_seconds=120) as c:
            status = await c.call_tool("status", {})
            gastos = await c.call_tool("gastos_listar", {"limite": 3, "campos": ["descricao", "valor"]})
            return c.server_info, status, gastos

    info, status, gastos = rodar_async(conversa)
    assert info.name == "tabimoney-demo"
    dados = json.loads(status.content[0].text)
    assert dados["demonstracao"] is True and "Marina" in dados["titulares"]
    assert len(json.loads(gastos.content[0].text)["lancamentos"]) == 3
