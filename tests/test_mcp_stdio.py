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

from .conftest import rodar_async

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("args", [["-m", "app.mcp_server", "--demo"], ["-m", "app.launch", "mcp", "--demo"]],
                         ids=["python -m app.mcp_server", "Tabimoney mcp"])
def test_servidor_por_stdio(args):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
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
