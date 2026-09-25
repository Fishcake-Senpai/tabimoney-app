from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"
REQUIRED_SCHEMA_OBJECTS = {
    "app_setting", "sync_run", "financial_account", "account_balance_snapshot",
    "cash_transaction", "instrument", "investment_event", "position_snapshot",
    "daily_quote", "reconciliation_note", "v_latest_position_per_account",
    "v_portfolio_positions", "v_asset_valuation", "v_portfolio_totals",
    "v_bank_latest_balances", "v_personal_totals", "v_position_reconciliation",
    "v_bank_balance_reconciliation", "fixed_income_snapshot", "benchmark_quote",
}
REQUIRED_SCHEMA_COLUMNS = {
    "sync_run": {"external_updated_at"},
    "cash_transaction": {"status", "category", "statement_ref"},
    "financial_account": {"credit_limit_cents", "available_limit_cents"},
    "fixed_income_snapshot": {"purchase_date"},
}


def data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    else:
        root = Path.home() / "AppData" / "Local"
    folder = root / "FinancasPessoais"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def database_path() -> Path:
    return data_dir() / "financas.sqlite3"


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 20000")
    return connection


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
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
    source = connect()
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return destination


def validate_database(path: Path) -> tuple[bool, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return False, "O arquivo está vazio ou não existe."
    try:
        connection = sqlite3.connect(path, timeout=5)
        try:
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
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False, "Não foi possível abrir esse arquivo como uma base SQLite válida."
    return True, "Base válida."


def restore_database(uploaded_bytes: bytes) -> Path:
    folder = data_dir()
    candidate = folder / "restore-candidate.sqlite3"
    candidate.write_bytes(uploaded_bytes)
    valid, reason = validate_database(candidate)
    if not valid:
        candidate.unlink(missing_ok=True)
        raise ValueError(reason)
    backup = create_backup()
    candidate.replace(database_path())
    return backup


def rows(query: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    with session() as connection:
        return connection.execute(query, parameters).fetchall()
