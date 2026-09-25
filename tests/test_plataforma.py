"""Windows e Mac: pasta de dados, cofre de senhas e pasta da IA.

Simula o outro sistema trocando só o `os`/`sys` que cada módulo enxerga (mexer no global afetaria o pytest).
No GitHub Actions estes testes rodam de verdade em Windows e Mac.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import agent_workspace, db, security

from .conftest import COFRE_REAL


def _simular(monkeypatch, modulo, nome_os: str, plataforma: str) -> None:
    monkeypatch.setattr(modulo, "os", SimpleNamespace(name=nome_os, environ=os.environ))
    if hasattr(modulo, "sys"):
        monkeypatch.setattr(modulo, "sys", SimpleNamespace(platform=plataforma))


@pytest.mark.parametrize("nome_os, plataforma, final", [
    ("nt", "win32", ("localappdata", "FinancasPessoais")),
    ("posix", "darwin", ("Library", "Application Support", "Tabimoney")),
    ("posix", "linux", ("xdg", "tabimoney")),
])
def test_pasta_de_dados_por_sistema(monkeypatch, nome_os, plataforma, final):
    _simular(monkeypatch, db, nome_os, plataforma)
    pasta = db.data_dir()
    assert pasta.parts[-len(final):] == final
    assert pasta.is_dir()


def test_banco_de_teste_nunca_e_o_real(dados_isolados):
    assert str(db.database_path()).startswith(str(dados_isolados))


@pytest.mark.parametrize("nome_os, plataforma, esperado", [
    ("nt", "win32", "Credential Manager do Windows"),
    ("posix", "darwin", "Porta-chaves (Keychain) do macOS"),
    ("posix", "linux", "chaveiro do sistema"),
])
def test_nome_do_cofre(monkeypatch, nome_os, plataforma, esperado):
    _simular(monkeypatch, security, nome_os, plataforma)
    assert security.vault_name() == esperado


def _backend(modulo: str, classe: str):
    return type(classe, (), {"__module__": modulo})()


@pytest.mark.parametrize("nome_os, plataforma, modulo, classe, aceito", [
    ("nt", "win32", "keyring.backends.Windows", "WinVaultKeyring", True),
    ("posix", "darwin", "keyring.backends.macOS", "Keyring", True),
    ("posix", "darwin", "keyrings.alt.file", "PlaintextKeyring", False),   # arquivo em texto: nunca
    ("nt", "win32", "keyring.backends.fail", "Keyring", False),
    ("posix", "darwin", "keyring.backends.Windows", "WinVaultKeyring", False),
])
def test_cofre_so_aceita_o_nativo(monkeypatch, nome_os, plataforma, modulo, classe, aceito):
    import keyring

    _simular(monkeypatch, security, nome_os, plataforma)
    monkeypatch.setattr(keyring, "get_keyring", lambda: _backend(modulo, classe))
    if aceito:
        assert COFRE_REAL() is keyring
    else:
        with pytest.raises(RuntimeError):
            COFRE_REAL()


def test_pasta_da_ia_no_windows(monkeypatch):
    _simular(monkeypatch, agent_workspace, "nt", "win32")
    pasta = agent_workspace.sync(Path("C:/Apps/Tabimoney.exe"))
    bat = (pasta / "financas.bat").read_text(encoding="utf-8")
    assert "Tabimoney.exe" in bat and " cli %*" in bat
    assert ".\\financas.bat" in (pasta / "AGENTS.md").read_text(encoding="utf-8")
    assert (pasta / ".claude" / "skills" / "financas" / "SKILL.md").is_file()
    assert (pasta / "docs" / "agente-financeiro.md").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="bit de execução só existe no Mac/Linux")
def test_financas_sh_e_executavel(monkeypatch):
    pasta = agent_workspace.sync(Path("/Applications/Tabimoney.app/Contents/MacOS/Tabimoney"))
    assert os.access(pasta / "financas.sh", os.X_OK)


def test_pasta_da_ia_no_mac(monkeypatch):
    _simular(monkeypatch, agent_workspace, "posix", "darwin")
    pasta = agent_workspace.sync(Path("/Applications/Tabimoney.app/Contents/MacOS/Tabimoney"))
    sh = (pasta / "financas.sh").read_text(encoding="utf-8")
    assert sh.startswith("#!/bin/sh") and 'exec "$EXE" cli "$@"' in sh
    agents = (pasta / "AGENTS.md").read_text(encoding="utf-8")
    assert "./financas.sh" in agents and "use `./financas.sh`" in agents
    assert not (pasta / "financas.bat").exists()
