from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Iterator

import sqlcipher3

from app import db_crypto


ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"
REQUIRED_SCHEMA_OBJECTS = {
    "app_setting", "sync_run", "financial_account", "account_balance_snapshot",
    "cash_transaction", "instrument", "investment_event", "position_snapshot",
    "daily_quote", "reconciliation_note", "v_latest_position_per_account",
    "v_portfolio_positions", "v_asset_valuation", "v_portfolio_totals",
    "v_bank_latest_balances", "v_personal_totals", "v_position_reconciliation",
    "v_bank_balance_reconciliation", "fixed_income_snapshot", "benchmark_quote",
    "household_member", "pluggy_connection", "pluggy_item",
}
REQUIRED_SCHEMA_COLUMNS = {
    "sync_run": {"external_updated_at"},
    "cash_transaction": {"status", "category", "statement_ref"},
    "financial_account": {"credit_limit_cents", "available_limit_cents", "member_id"},
    "fixed_income_snapshot": {"purchase_date"},
}


def data_dir() -> Path:
    """Pasta dos dados: %LOCALAPPDATA%\\FinancasPessoais no Windows, ~/Library/Application Support/Tabimoney no
    macOS, $XDG_DATA_HOME/tabimoney (ou ~/.local/share/tabimoney) no Linux."""
    if os.name == "nt":
        folder = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "FinancasPessoais"
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Tabimoney"
    else:
        folder = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "tabimoney"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# Troca a base só no contexto atual (uma requisição, um comando): é o que isola a demonstração (app/demo.py).
_database_override: ContextVar[Path | None] = ContextVar("database_override", default=None)


def database_path() -> Path:
    return _database_override.get() or data_dir() / "financas.sqlite3"


@contextmanager
def using_database(path: Path) -> Iterator[Path]:
    """Tudo o que roda dentro do bloco (e nas threads que ele abre) lê e grava em outra base."""
    token = _database_override.set(path)
    try:
        yield path
    finally:
        _database_override.reset(token)


def connect(path: Path | None = None) -> sqlcipher3.Connection:
    """Abre a base criptografada, migrando uma base plaintext antiga na primeira vez."""
    db_path = path or database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key, _ = db_crypto.prepare_database(db_path)
    return db_crypto.connect(db_path, key, timeout=20, verify=False)


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlcipher3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlcipher3.Connection]:
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with session() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in sorted(MIGRATIONS_DIR.glob("[0-9]*_*.sql")):
            version = int(migration.name.split("_", maxsplit=1)[0])
            if version in applied:
                continue
            sql = migration.read_text(encoding="utf-8")
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT OR IGNORE INTO schema_migrations(version) VALUES ({version});\nCOMMIT;"
            )
        profile = connection.execute(
            "SELECT value FROM app_setting WHERE key = 'db_crypto_profile'"
        ).fetchone()
        if profile and profile["value"] != db_crypto.CRYPTO_PROFILE:
            raise db_crypto.DatabaseCryptoError(
                "Esta base usa um perfil de criptografia que esta versão do app não conhece."
            )
        connection.execute(
            "INSERT OR IGNORE INTO app_setting(key, value) VALUES ('db_crypto_profile', ?)",
            (db_crypto.CRYPTO_PROFILE,),
        )
        connection.commit()


def get_setting(key: str, default: str = "") -> str:
    with session() as connection:
        row = connection.execute(
            "SELECT value FROM app_setting WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with transaction() as connection:
        connection.execute(
            "INSERT INTO app_setting(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )


def create_backup() -> Path:
    backup_dir = data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"financas-backup-{stamp}.sqlite3"
    counter = 1
    while destination.exists():
        destination = backup_dir / f"financas-backup-{stamp}-{counter}.sqlite3"
        counter += 1
    source_path = database_path()
    key, _ = db_crypto.prepare_database(source_path)
    db_crypto.backup_database(source_path, destination, key)
    return destination


def encrypt_legacy_backups() -> dict[str, list[str]]:
    """Criptografa os backups antigos em texto claro, exceto o backup de uma atualização em andamento."""
    folder = data_dir() / "backups"
    try:
        key = db_crypto.get_or_create_key(database_path(), create=False)
    except db_crypto.DatabaseCryptoError:
        return {"criptografados": [], "falharam": ["chave da base não disponível"], "ignorados": []}
    skip: set[Path] = set()
    try:
        state = json.loads((data_dir() / "atualizacao.json").read_text(encoding="utf-8"))
        if state.get("estado") not in ("concluida", "revertida") and state.get("backup"):
            skip.add(Path(state["backup"]))
    except (OSError, ValueError, TypeError):
        pass
    return db_crypto.encrypt_legacy_backups(folder, key, skip)


def _validate_connection(connection) -> tuple[bool, str]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        return False, "A verificação de integridade do SQLite falhou."
    has_schema = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not has_schema:
        return False, "O arquivo não contém o esquema desta aplicação."
    versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    current_version = max((row[0] for row in versions), default=0)
    expected_version = max(
        (int(file.name.split("_", maxsplit=1)[0]) for file in MIGRATIONS_DIR.glob("[0-9]*_*.sql")),
        default=0,
    )
    if current_version < expected_version:
        return False, "A versão do esquema não é compatível com esta aplicação."
    if current_version > expected_version:
        return False, "O backup foi criado por uma versão mais recente do aplicativo."
    present = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    missing = REQUIRED_SCHEMA_OBJECTS - present
    if missing:
        return False, "O esquema está incompleto e não pode ser restaurado com esta versão."
    for table_name, expected_columns in REQUIRED_SCHEMA_COLUMNS.items():
        actual_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
        }
        if not expected_columns <= actual_columns:
            return False, "O esquema está incompleto e não pode ser restaurado com esta versão."
    for view_name in (
        "v_latest_position_per_account", "v_portfolio_positions", "v_asset_valuation",
        "v_portfolio_totals", "v_bank_latest_balances", "v_personal_totals",
        "v_position_reconciliation", "v_bank_balance_reconciliation",
    ):
        connection.execute(f"SELECT * FROM {view_name} LIMIT 0").fetchall()
    return True, "Base válida."


def validate_database(path: Path) -> tuple[bool, str]:
    """Valida uma base plaintext antiga ou uma base criptografada com a chave do cofre."""
    if not path.is_file() or path.stat().st_size == 0:
        return False, "O arquivo está vazio ou não existe."
    if db_crypto.is_plaintext(path):
        try:
            connection = sqlite3.connect(path, timeout=5)
            try:
                connection.execute("PRAGMA trusted_schema = OFF")
                return _validate_connection(connection)
            finally:
                connection.close()
        except (sqlite3.DatabaseError, sqlcipher3.DatabaseError):
            return False, "Não foi possível abrir esse arquivo como uma base SQLite válida."
    try:
        key = db_crypto.get_or_create_key(path, create=False)
        connection = db_crypto.connect(path, key, timeout=5)
    except db_crypto.DatabaseKeyError:
        return False, "A chave de criptografia não abre esse backup. Ele pode ser de outro computador."
    except db_crypto.DatabaseCryptoError:
        return False, "Não foi possível abrir esse arquivo como uma base criptografada válida."
    except OSError:
        return False, "Não foi possível ler esse arquivo."
    try:
        problems = connection.execute("PRAGMA cipher_integrity_check").fetchall()
        if problems:
            return False, "A verificação de autenticação da base criptografada falhou."
        return _validate_connection(connection)
    except (sqlite3.DatabaseError, sqlcipher3.DatabaseError):
        return False, "Não foi possível abrir esse arquivo como uma base SQLite válida."
    finally:
        connection.close()


def _prepare_restore_file(source: Path, destination: Path) -> Path:
    """Aceita backup plaintext antigo ou criptografado atual e devolve uma cópia criptografada pronta para entrar."""
    valid, reason = validate_database(source)
    if not valid:
        raise ValueError(reason)
    key = db_crypto.get_or_create_key(destination)
    staged = destination.with_name(destination.name + ".restore-staged")
    staged.unlink(missing_ok=True)
    try:
        if db_crypto.is_plaintext(source):
            db_crypto.encrypt_copy(source, staged, key)
        else:
            shutil.copy2(source, staged)
        valid, reason = validate_database(staged)
        if not valid:
            raise ValueError(reason)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def restore_database(uploaded_bytes: bytes) -> Path:
    folder = data_dir()
    candidate = folder / "restore-candidate.sqlite3"
    candidate.write_bytes(uploaded_bytes)
    prepared: Path | None = None
    try:
        prepared = _prepare_restore_file(candidate, database_path())
        backup = create_backup()
        db_crypto.remove_sidecars(database_path())
        prepared.replace(database_path())
        db_crypto.invalidate(database_path())
        if prepared != candidate:
            prepared.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        return backup
    except Exception:
        candidate.unlink(missing_ok=True)
        if prepared and prepared != candidate:
            prepared.unlink(missing_ok=True)
        raise


def restore_file(backup: Path) -> None:
    """Restaura um backup do atualizador, aceitando o plaintext da versão anterior e o criptografado novo."""
    prepared = _prepare_restore_file(backup, database_path())
    try:
        db_crypto.remove_sidecars(database_path())
        prepared.replace(database_path())
    finally:
        prepared.unlink(missing_ok=True)
    db_crypto.invalidate(database_path())


def rows(query: str, parameters: tuple[object, ...] = ()) -> list[sqlcipher3.Row]:
    with session() as connection:
        return connection.execute(query, parameters).fetchall()
