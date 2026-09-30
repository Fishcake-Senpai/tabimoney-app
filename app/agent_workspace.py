"""Pasta da IA (versão de transição): o jeito antigo de usar a IA com o executável, antes do servidor MCP.

A cada abertura, o executável grava na pasta Tabimoney do usuário (%USERPROFILE%\\Tabimoney no Windows,
~/Tabimoney no Mac) um AGENTS.md que aponta para Configurações › Conectar à IA, os roteiros (app/agente/roteiros)
com a tabela ferramenta MCP → comando da CLI, o contrato e o atalho da linha de comando que chama `Tabimoney cli`
(financas.bat no Windows, financas.sh no Mac). As skills que versões antigas gravaram em .claude/skills são
apagadas. A pasta sai numa versão futura; até lá, quem ainda abre o agente aqui continua sendo atendido.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from app import __version__, agente

ROOT = Path(__file__).resolve().parent.parent  # no executável, é a pasta extraída (sys._MEIPASS)
MANAGED_SKILL_PREFIX = "financas"


def folder() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Tabimoney"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != text:
        path.write_text(text, encoding="utf-8", newline="")


def _cli_wrapper(target: Path, exe: Path) -> str:
    """Grava o atalho da linha de comando e devolve como os roteiros devem chamá-lo."""
    if os.name == "nt":
        _write(target / "financas.bat", (
            "@echo off\r\n"
            "rem Gerado pelo Tabimoney; é atualizado toda vez que o app abre.\r\n"
            f'if not exist "{exe}" (\r\n'
            "  echo {\"erro\": \"Tabimoney.exe nao encontrado. Abra o Tabimoney uma vez para atualizar este atalho.\"}\r\n"
            "  exit /b 1\r\n"
            ")\r\n"
            f'"{exe}" cli %*\r\n'
        ))
        return ".\\financas.bat"
    script = target / "financas.sh"
    quoted = str(exe).replace("'", "'\\''")
    _write(script, (
        "#!/bin/sh\n"
        "# Gerado pelo Tabimoney; é atualizado toda vez que o app abre.\n"
        f"EXE='{quoted}'\n"
        'if [ ! -x "$EXE" ]; then\n'
        '  echo \'{"erro": "Tabimoney não encontrado. Abra o Tabimoney uma vez para atualizar este atalho."}\'\n'
        "  exit 1\n"
        "fi\n"
        'exec "$EXE" cli "$@"\n'
    ))
    script.chmod(0o755)
    return "./financas.sh"


def _tabela(command: str) -> str:
    from app.mcp_server.ferramentas import EQUIVALENTE_CLI

    lines = ["| Ferramenta do MCP | Comando |", "|---|---|"]
    for tool, cli in EQUIVALENTE_CLI.items():
        if cli:
            lines.append(f"| `{tool}` | `{command} {cli}` |")
    lines.append(f"| `titular: \"Ana\"` (em qualquer ferramenta) | `{command} --titular Ana <comando>` |")
    lines.append("| `roteiro` | leia o arquivo em `roteiros/` |")
    return "\n".join(lines)


def sync(exe: Path) -> Path:
    target = folder()
    target.mkdir(parents=True, exist_ok=True)
    command = _cli_wrapper(target, exe)
    agents = (ROOT / "docs" / "agentes" / "pasta-ia" / "AGENTS.md").read_text(encoding="utf-8")
    agents = agents.replace("{{TABELA}}", _tabela(command))
    if command != ".\\financas.bat":
        # os roteiros foram escritos para Windows; no Mac/Linux o atalho é financas.sh
        agents = agents.replace(".\\financas.bat", command).replace("`financas.bat`", f"`{command[2:]}`")
        agents += (f"\n## Sistema\n\nEste computador não é Windows: onde os roteiros disserem `.\\financas.bat`, "
                   f"use `{command}` (mesmos argumentos, mesma saída em JSON).\n")
    _write(target / "AGENTS.md", agents)
    _write(target / "CLAUDE.md", "@AGENTS.md\n")
    _write(target / ".tabimoney-versao", __version__ + "\n")

    skills = target / ".claude" / "skills"  # versões até a 0.12 gravavam as skills aqui
    if skills.exists():
        for old in skills.iterdir():
            if old.is_dir() and old.name.startswith(MANAGED_SKILL_PREFIX):
                shutil.rmtree(old)

    for nome in agente.ROTEIROS:
        _write(target / "roteiros" / f"{nome}.md", (agente.ROTEIROS_DIR / f"{nome}.md").read_text(encoding="utf-8"))

    docs_dst = target / "docs"
    _write(docs_dst / "agente-financeiro.md", (ROOT / "docs" / "agente-financeiro.md").read_text(encoding="utf-8"))
    shutil.copytree(ROOT / "docs" / "agentes", docs_dst / "agentes", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("pasta-ia"))
    (target / "trabalho").mkdir(exist_ok=True)
    return target
