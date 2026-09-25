"""Pasta de trabalho da IA para quem usa o executável (Tabimoney.exe / Tabimoney.app), sem o repositório.

A cada abertura, o executável grava na pasta Tabimoney do usuário (%USERPROFILE%\\Tabimoney no Windows,
~/Tabimoney no Mac) as instruções (AGENTS.md), as skills, o contrato e um atalho da linha de comando que chama
`Tabimoney cli` (financas.bat no Windows, financas.sh no Mac). O agente (Claude Code, Codex…) aberto nessa pasta
trabalha igual ao repositório. Tudo vem de dentro do executável, então atualizar o app atualiza as skills.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from app import __version__

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


def sync(exe: Path) -> Path:
    target = folder()
    target.mkdir(parents=True, exist_ok=True)
    command = _cli_wrapper(target, exe)
    agents = (ROOT / "docs" / "agentes" / "pasta-ia" / "AGENTS.md").read_text(encoding="utf-8")
    if command != ".\\financas.bat":
        # os roteiros foram escritos para Windows; no Mac/Linux o atalho é financas.sh
        agents = agents.replace(".\\financas.bat", command).replace("`financas.bat`", f"`{command[2:]}`")
        agents += (f"\n## Sistema\n\nEste computador não é Windows: onde os roteiros disserem `.\\financas.bat`, "
                   f"use `{command}` (mesmos argumentos, mesma saída em JSON).\n")
    _write(target / "AGENTS.md", agents)
    _write(target / "CLAUDE.md", "@AGENTS.md\n")
    _write(target / ".tabimoney-versao", __version__ + "\n")

    skills_src, skills_dst = ROOT / ".claude" / "skills", target / ".claude" / "skills"
    bundled = {p.name for p in skills_src.iterdir() if p.is_dir()}
    if skills_dst.exists():
        for old in skills_dst.iterdir():
            if old.is_dir() and old.name.startswith(MANAGED_SKILL_PREFIX) and old.name not in bundled:
                shutil.rmtree(old)
    shutil.copytree(skills_src, skills_dst, dirs_exist_ok=True)

    docs_dst = target / "docs"
    _write(docs_dst / "agente-financeiro.md", (ROOT / "docs" / "agente-financeiro.md").read_text(encoding="utf-8"))
    shutil.copytree(ROOT / "docs" / "agentes", docs_dst / "agentes", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("pasta-ia"))
    (target / "trabalho").mkdir(exist_ok=True)
    return target
