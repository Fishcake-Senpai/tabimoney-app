from __future__ import annotations

import os


SERVICE_NAME = "FinancasPessoaisLocal"


def _windows_credential_manager():
    if os.name != "nt":
        raise RuntimeError("As credenciais devem ser guardadas no Credential Manager do Windows.")
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Instale as dependências do aplicativo para habilitar o cofre local.") from exc
    backend = keyring.get_keyring()
    backend_name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
    if "windows" not in backend_name and "winvault" not in backend_name:
        raise RuntimeError(
            "O cofre seguro do Windows não está disponível. Nenhuma credencial foi gravada."
        )
    return keyring


def save_secret(name: str, value: str) -> None:
    if not value:
        return
    keyring = _windows_credential_manager()
    keyring.set_password(SERVICE_NAME, name, value)


def get_secret(name: str) -> str | None:
    keyring = _windows_credential_manager()
    return keyring.get_password(SERVICE_NAME, name)


def delete_secret(name: str) -> None:
    keyring = _windows_credential_manager()
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
