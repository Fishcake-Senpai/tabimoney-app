"""SQLCipher: chave no cofre, migração verificada e backups criptografados."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db, db_crypto


def _legacy_database(path: Path) -> None:
    """Cria uma base plaintext com o esquema completo, como uma instalação anterior à criptografia."""
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        for migration in sorted(db.MIGRATIONS_DIR.glob("[0-9]*_*.sql")):
            version = int(migration.name.split("_", maxsplit=1)[0])
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        connection.execute(
            "INSERT INTO app_setting(key, value) VALUES ('teste', 'antes')"
        )
        connection.commit()
    finally:
        connection.close()


def test_init_db_grava_o_perfil_criptografico(tmp_path):
    path = tmp_path / "base.sqlite3"
    with db.using_database(path):
        db.init_db()
        assert db.get_setting("db_crypto_profile") == db_crypto.CRYPTO_PROFILE


def test_a_chave_fica_no_cofre_e_a_base_nova_nao_e_plaintext(tmp_path, cofre):
    path = tmp_path / "nova.sqlite3"
    db.init_db()
    with db.using_database(path):
        db.init_db()
    assert not db_crypto.is_plaintext(path)
    assert path.read_bytes()[:16] != db_crypto.RAW_SQLITE_MAGIC
    assert ("FinancasPessoaisLocal", db_crypto.KEY_SECRET) in cofre.dados
    with db.using_database(path):
        assert db.get_setting("nao_existe", "ok") == "ok"


def test_migra_plaintext_com_fingerprint_e_preserva_os_dados(tmp_path):
    path = tmp_path / "antiga.sqlite3"
    _legacy_database(path)
    assert db_crypto.is_plaintext(path)
    connection = sqlite3.connect(path)
    try:
        before = db_crypto.fingerprint(connection)
    finally:
        connection.close()

    key, result = db_crypto.prepare_database(path)

    assert result is not None and result.migrated
    assert not db_crypto.is_plaintext(path)
    assert result.legacy is not None and result.legacy.exists()
    connection = db_crypto.connect(path, key)
    try:
        assert db_crypto.fingerprint(connection) == before
        assert connection.execute("SELECT value FROM app_setting WHERE key='teste'").fetchone()[0] == "antes"
    finally:
        connection.close()
    db_crypto.finalize_pending(path)
    assert not result.legacy.exists()
    assert not db_crypto._state_path(path).exists()


def test_startup_do_app_migra_a_base_plaintext(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    default = db.database_path()
    default.unlink(missing_ok=True)
    _legacy_database(default)
    db_crypto.invalidate(default)
    with TestClient(app, base_url=f"http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as client:
        assert client.get("/").status_code == 200
        assert not db_crypto.is_plaintext(default)
        assert db.get_setting("teste") == "antes"


def test_rollback_de_inicializacao_devolve_o_plaintext(tmp_path):
    path = tmp_path / "antiga.sqlite3"
    _legacy_database(path)
    _key, result = db_crypto.prepare_database(path)
    assert result is not None and not db_crypto.is_plaintext(path)
    db_crypto.rollback_pending(path)
    assert db_crypto.is_plaintext(path)
    assert list(tmp_path.glob("antiga.sqlite3.encrypted-failed-*"))


def test_recupera_estado_deixado_entre_o_rename_e_o_export(tmp_path):
    path = tmp_path / "antiga.sqlite3"
    _legacy_database(path)
    key = db_crypto.get_or_create_key(path)
    legacy = tmp_path / "antiga.sqlite3.pre-encryption-teste"
    temporary = tmp_path / "antiga.sqlite3.encrypted.tmp"
    db_crypto._write_state(path, {
        "state": "preparing", "legacy": str(legacy), "temporary": str(temporary),
        "fingerprint": "x", "profile": db_crypto.CRYPTO_PROFILE,
    })
    db_crypto._move_no_overwrite(path, legacy)
    _key, result = db_crypto.prepare_database(path)
    assert result is not None and result.migrated
    connection = db_crypto.connect(path, key)
    try:
        assert connection.execute("SELECT value FROM app_setting WHERE key='teste'").fetchone()[0] == "antes"
    finally:
        connection.close()
    db_crypto.finalize_pending(path)


def test_migracao_que_falha_volta_ao_plaintext(tmp_path, monkeypatch):
    path = tmp_path / "antiga.sqlite3"
    _legacy_database(path)
    original = db_crypto.encrypt_copy

    def falhar(*_args, **_kwargs):
        raise db_crypto.MigrationError("falha simulada")

    monkeypatch.setattr(db_crypto, "encrypt_copy", falhar)
    with pytest.raises(db_crypto.MigrationError):
        db_crypto.prepare_database(path)
    assert db_crypto.is_plaintext(path)
    monkeypatch.setattr(db_crypto, "encrypt_copy", original)


def test_backup_e_restauracao_criptografados(tmp_path):
    db.set_setting("antes", "1")
    backup = db.create_backup()
    assert not db_crypto.is_plaintext(backup)
    ok, _ = db.validate_database(backup)
    assert ok
    with db.transaction() as connection:
        connection.execute("DELETE FROM app_setting WHERE key = 'antes'")
    db.restore_file(backup)
    assert db.get_setting("antes") == "1"


def test_restaura_backup_plaintext_antigo_criptografando(tmp_path):
    old = tmp_path / "backup-antigo.sqlite3"
    _legacy_database(old)
    connection = sqlite3.connect(old)
    try:
        connection.execute("INSERT INTO app_setting(key, value) VALUES ('antigo', 'sim')")
        connection.commit()
    finally:
        connection.close()

    db.restore_file(old)

    assert db.get_setting("antigo") == "sim"
    assert not db_crypto.is_plaintext(db.database_path())


def test_chave_errada_nao_abre_a_base(tmp_path):
    path = tmp_path / "base.sqlite3"
    with db.using_database(path):
        db.init_db()
        db.set_setting("x", "1")
    wrong = db_crypto.DatabaseKey(b"\x00" * 32)
    with pytest.raises(db_crypto.DatabaseKeyError):
        db_crypto.connect(path, wrong)


def test_cipher_integrity_check_esta_limpo(tmp_path):
    path = tmp_path / "base.sqlite3"
    with db.using_database(path):
        db.init_db()
        db.set_setting("x", "1")
    key = db_crypto.get_or_create_key(path)
    connection = db_crypto.connect(path, key)
    try:
        assert connection.execute("PRAGMA cipher_integrity_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_criptografa_backups_antigos_e_respeita_o_skip(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    first = folder / "backup-1.sqlite3"
    second = folder / "backup-2.sqlite3"
    _legacy_database(first)
    _legacy_database(second)
    key = db_crypto.get_or_create_key(tmp_path / "base.sqlite3")
    result = db_crypto.encrypt_legacy_backups(folder, key, skip={second})
    assert [Path(p).name for p in result["criptografados"]] == ["backup-1.sqlite3"]
    assert not db_crypto.is_plaintext(first)
    assert db_crypto.is_plaintext(second)
    connection = db_crypto.connect(first, key)
    try:
        assert connection.execute("SELECT value FROM app_setting WHERE key='teste'").fetchone()[0] == "antes"
    finally:
        connection.close()


def test_chave_ausente_nao_gera_chave_nova_para_base_criptografada(tmp_path, cofre):
    path = tmp_path / "base.sqlite3"
    with db.using_database(path):
        db.init_db()
    cofre.dados.pop(("FinancasPessoaisLocal", db_crypto.KEY_SECRET))
    db_crypto.clear_key_cache()
    db_crypto.invalidate(path)
    with pytest.raises(db_crypto.DatabaseKeyError):
        db_crypto.prepare_database(path)
    assert ("FinancasPessoaisLocal", db_crypto.KEY_SECRET) not in cofre.dados


def test_chave_gerada_e_estavel(tmp_path, cofre):
    key1 = db_crypto.get_or_create_key(tmp_path / "uma.sqlite3")
    db_crypto.clear_key_cache()
    key2 = db_crypto.get_or_create_key(tmp_path / "outra.sqlite3")
    assert key1 == key2
    assert cofre.dados[("FinancasPessoaisLocal", db_crypto.KEY_SECRET)] == key1.hex
