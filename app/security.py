"""Segredos (Pluggy, brapi) no cofre nativo do sistema: Credential Manager no Windows, Porta-chaves no macOS.

Só aceita o cofre nativo. Se o keyring cair num backend inseguro (arquivo em texto, nulo), nada é gravado.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

SERVICE_NAME = "FinancasPessoaisLocal"

# trecho do módulo do backend do keyring aceito em cada sistema
_NATIVE = {
    "win32": ("windows", "winvault"),
    "darwin": ("macos",),
    "linux": ("secretservice", "libsecret", "kwallet"),
}


def vault_name() -> str:
    if os.name == "nt":
        return "Credential Manager do Windows"
    if sys.platform == "darwin":
        return "Porta-chaves (Keychain) do macOS"
    return "chaveiro do sistema"


def _backend_names(backend) -> list[str]:
    inner = getattr(backend, "backends", None)  # ChainerBackend junta vários
    items = list(inner) if inner else [backend]
    return [f"{type(b).__module__}.{type(b).__name__}".lower() for b in items]


# Cofre trocado só no contexto atual: a demonstração usa um cofre em memória e nunca toca no do sistema.
_vault_override: ContextVar[Any] = ContextVar("vault_override", default=None)


@contextmanager
def using_vault(vault: Any) -> Iterator[Any]:
    token = _vault_override.set(vault)
    try:
        yield vault
    finally:
        _vault_override.reset(token)


def _vault():
    """O cofre do contexto (a demonstração usa um em memória) ou, fora dele, o do sistema."""
    override = _vault_override.get()
    return override if override is not None else _system_vault()


def _system_vault():
    accepted = _NATIVE.get("win32" if os.name == "nt" else sys.platform)
    if not accepted:
        raise RuntimeError("Este sistema não tem um cofre de senhas suportado. Nenhuma credencial foi gravada.")
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Instale as dependências do aplicativo para habilitar o cofre local.") from exc
    names = _backend_names(keyring.get_keyring())
    if not any(key in name for name in names for key in accepted):
        raise RuntimeError(f"O {vault_name()} não está disponível. Nenhuma credencial foi gravada.")
    return keyring


def save_secret(name: str, value: str) -> None:
    if not value:
        return
    keyring = _vault()
    keyring.set_password(SERVICE_NAME, name, value)


def get_secret(name: str) -> str | None:
    keyring = _vault()
    return keyring.get_password(SERVICE_NAME, name)


def delete_secret(name: str) -> None:
    keyring = _vault()
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
