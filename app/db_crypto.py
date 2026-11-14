"""Criptografia da base local com SQLCipher e migração verificada do SQLite plaintext.

A chave é aleatória (32 bytes) e fica no cofre nativo do sistema. O dia a dia usa a chave raw, sem KDF por
conexão; o KDF de 256 mil iterações fica para o backup portátil com passphrase (Fase 2).

Toda conexão passa por `connect()`, que aplica o perfil criptográfico antes de qualquer consulta. A migração de
uma base antiga acontece uma vez, com cópia plaintext, `sqlcipher_export`, fingerprint lógico e troca atômica.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import struct
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import sqlcipher3

from app import security

RAW_SQLITE_MAGIC = b"SQLite format 3\0"
CRYPTO_PROFILE = "sqlcipher4-v1"
CIPHER_PAGE_SIZE = 4096
CIPHER_KDF_ITER = 256_000
KEY_SECRET = "database_key_v1"
STATE_SUFFIX = ".migration.json"

# Um único lock por processo para preparar/migrar; o lock de arquivo cobre outros processos.
_local_lock = threading.RLock()
_ready: set[Path] = set()
_pending: dict[Path, "MigrationResult"] = {}


class DatabaseCryptoError(RuntimeError):
    """Falha ao abrir, validar ou migrar a base criptografada."""


class DatabaseKeyError(DatabaseCryptoError):
    """A chave do cofre não abre esta base (ou o arquivo está corrompido)."""


class MigrationError(DatabaseCryptoError):
    """A migração não pôde ser concluída com segurança."""


@dataclass(frozen=True)
class DatabaseKey:
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != 32:
            raise ValueError("A chave do banco precisa ter 32 bytes.")

    @property
    def hex(self) -> str:
        return self.raw.hex()

    @property
    def pragma(self) -> str:
        # A chave fica entre aspas duplas para o parser do SQLCipher; o conteúdo é um literal raw x'...'.
        return f'PRAGMA key = "x\'{self.hex}\'"'

    def __repr__(self) -> str:  # nunca mostrar a chave em log/traceback
        return "DatabaseKey(***)"


@dataclass(frozen=True)
class MigrationResult:
    database: Path
    legacy: Path | None
    migrated: bool


def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _read_header(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read(len(RAW_SQLITE_MAGIC))


def is_plaintext(path: Path) -> bool:
    """True só para um arquivo SQLite comum; um arquivo vazio ou criptografado retorna False."""
    try:
        return path.is_file() and path.stat().st_size >= 16 and _read_header(path) == RAW_SQLITE_MAGIC
    except OSError:
        return False


def remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows: o ACL da pasta já restringe; não transformar isso em falha da migração


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb") as file:
            os.fsync(file.fileno())
    except OSError:
        pass


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Lock exclusivo entre processos, sem dependência externa (msvcrt no Windows, flock no Mac/Linux)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            for _ in range(100):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise MigrationError("Outra cópia do Tabimoney está preparando a base. Tente de novo em instantes.")
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _app_lock_path(path: Path) -> Path:
    return path.parent / "tabimoney.lock"


def _ensure_no_running_app(path: Path) -> None:
    """A migração não pode trocar o arquivo enquanto outro Tabimoney o tem aberto."""
    lock = _app_lock_path(path)
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(info.get("pid") or 0)
    except (OSError, ValueError, TypeError):
        return
    if pid and pid != os.getpid() and _pid_alive(pid):
        raise MigrationError(
            "O Tabimoney está aberto em outro processo. Feche-o e abra de novo para concluir a proteção da base."
        )


def _key_lock_path(path: Path) -> Path:
    return path.parent / "db-key.lock"


def get_or_create_key(path: Path, create: bool = True) -> DatabaseKey:
    """Lê a chave do cofre ou gera uma nova, serializando a criação entre processos.

    A chave não é derivada de senha: são 32 bytes aleatórios guardados no Credential Manager/Keychain. Por isso o
    dia a dia usa a forma raw do SQLCipher; o KDF só é usado no backup portátil com passphrase.
    """
    vault = security._vault()  # o cofre do contexto (a demo usa um em memória)
    cache_key = (path.parent.resolve(), id(vault))
    with _local_lock:
        cached = _KEY_CACHE.get(cache_key)
        if cached is not None:
            return cached
        with _file_lock(_key_lock_path(path)):
            value = security.get_secret(KEY_SECRET)
            if value:
                try:
                    key = DatabaseKey(bytes.fromhex(value))
                except ValueError as exc:
                    raise DatabaseKeyError(
                        "A chave de criptografia guardada no cofre do sistema está inválida."
                    ) from exc
            elif not create:
                raise DatabaseKeyError(
                    "A chave de criptografia não está no cofre do sistema. Sem ela, esta base não pode ser aberta."
                )
            else:
                key = DatabaseKey(secrets.token_bytes(32))
                security.save_secret(KEY_SECRET, key.hex)
                # Relê para detectar uma corrida com outro processo que gravou primeiro.
                saved = security.get_secret(KEY_SECRET)
                if not saved:
                    raise DatabaseKeyError(
                        "Não foi possível guardar a chave da base no cofre do sistema. A base não foi criada."
                    )
                if saved != key.hex:
                    try:
                        key = DatabaseKey(bytes.fromhex(saved))
                    except ValueError as exc:
                        raise DatabaseKeyError(
                            "A chave de criptografia guardada no cofre do sistema está inválida."
                        ) from exc
        _KEY_CACHE[cache_key] = key
        return key


_KEY_CACHE: dict[tuple[Path, int], DatabaseKey] = {}


def clear_key_cache() -> None:
    with _local_lock:
        _KEY_CACHE.clear()


def _pragma_batch(connection: sqlcipher3.Connection, key: DatabaseKey) -> None:
    connection.execute(key.pragma)
    connection.execute("PRAGMA cipher_compatibility = 4")
    connection.execute(f"PRAGMA cipher_page_size = {CIPHER_PAGE_SIZE}")
    connection.execute(f"PRAGMA kdf_iter = {CIPHER_KDF_ITER}")
    connection.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
    connection.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
    connection.execute("PRAGMA cipher_plaintext_header_size = 0")
    connection.execute("PRAGMA cipher_memory_security = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 20000")
    connection.execute("PRAGMA secure_delete = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA trusted_schema = OFF")


def connect(path: Path, key: DatabaseKey, timeout: int = 20, verify: bool = True) -> sqlcipher3.Connection:
    """Abre uma conexão criptografada já com o perfil aplicado.

    `verify=True` faz a consulta que confere a chave; o fluxo normal do app chama `prepare_database()` uma vez e
    depois abre conexões com `verify=False`, porque a chave já foi conferida e a consulta de esquema custa caro em
    bases grandes.
    """
    exists = path.exists()
    connection = sqlcipher3.connect(path, timeout=timeout)
    connection.row_factory = sqlcipher3.Row
    try:
        _pragma_batch(connection, key)
        if verify:
            connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()
        if not exists:
            _chmod_private(path)
    except sqlcipher3.DatabaseError as exc:
        connection.close()
        raise DatabaseKeyError(
            "A chave de criptografia não abre esta base. O arquivo pode ser de outro computador ou estar corrompido."
        ) from exc
    return connection


def verify_encrypted(path: Path, key: DatabaseKey, full: bool = False) -> None:
    connection = connect(path, key, timeout=5)
    try:
        if full:
            problems = connection.execute("PRAGMA cipher_integrity_check").fetchall()
            if problems:
                raise DatabaseKeyError("A verificação de autenticação da base criptografada falhou.")
    finally:
        connection.close()


def _tagged(hasher: Any, tag: str, value: bytes) -> None:
    hasher.update(tag.encode("utf-8"))
    hasher.update(len(value).to_bytes(8, "big"))
    hasher.update(value)


def _value_bytes(value: Any) -> bytes:
    if value is None:
        return b"n"
    if isinstance(value, bool):
        return b"i" + int(value).to_bytes(8, "big", signed=True)
    if isinstance(value, int):
        size = max(1, (value.bit_length() + 8) // 8)
        return b"i" + value.to_bytes(size, "big", signed=True)
    if isinstance(value, float):
        return b"f" + struct.pack(">d", value)
    if isinstance(value, str):
        return b"t" + value.encode("utf-8")
    if isinstance(value, bytes):
        return b"b" + value
    return b"?" + str(value).encode("utf-8")


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprint(connection: Any) -> str:
    """Fingerprint lógico versionado: esquema + multiconjunto de linhas, independente da ordem física."""
    hasher = hashlib.sha256()
    _tagged(hasher, "fingerprint-version", b"1")
    objects = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
    ).fetchall()
    _tagged(hasher, "schema-object-count", str(len(objects)).encode("ascii"))
    for obj in objects:
        for part in obj:
            _tagged(hasher, "schema-object", _value_bytes(part))

    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for table in tables:
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({_quote_identifier(table)})")]
        _tagged(hasher, "table", table.encode("utf-8"))
        _tagged(hasher, "columns", "\x1f".join(columns).encode("utf-8"))
        row_hashes: list[bytes] = []
        for row in connection.execute(f"SELECT * FROM {_quote_identifier(table)}"):
            row_hasher = hashlib.sha256()
            for value in row:
                _tagged(row_hasher, "value", _value_bytes(value))
            row_hashes.append(row_hasher.digest())
        row_hashes.sort()
        _tagged(hasher, "row-count", str(len(row_hashes)).encode("ascii"))
        for digest in row_hashes:
            hasher.update(digest)
    return hasher.hexdigest()


def _state_path(path: Path) -> Path:
    return path.with_name(path.name + STATE_SUFFIX)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(_state_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    destination = _state_path(path)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _chmod_private(temporary)
    _fsync_file(temporary)
    os.replace(temporary, destination)
    _fsync_dir(destination.parent)


def _remove_state(path: Path) -> None:
    _state_path(path).unlink(missing_ok=True)


def _move_no_overwrite(source: Path, destination: Path) -> None:
    """Move sem sobrescrever. No Mac/Linux usa hardlink+unlink; no Windows, rename falha se o destino existir."""
    if destination.exists():
        raise FileExistsError(str(destination))
    if os.name == "nt":
        os.rename(source, destination)
    else:
        try:
            os.link(source, destination)
        except OSError:
            if destination.exists():
                raise FileExistsError(str(destination))
            os.rename(source, destination)
        else:
            os.unlink(source)
    _fsync_dir(destination.parent)


def encrypt_copy(source: Path, destination: Path, key: DatabaseKey) -> None:
    """Exporta uma base plaintext ou criptografada para uma nova base criptografada."""
    destination.unlink(missing_ok=True)
    connection = sqlcipher3.connect(destination)
    try:
        _pragma_batch(connection, key)
        connection.execute("ATTACH DATABASE ? AS origem KEY ''", (str(source),))
        connection.execute("SELECT sqlcipher_export('main', 'origem')")
        connection.execute("DETACH DATABASE origem")
        connection.commit()
    except sqlcipher3.DatabaseError as exc:
        connection.close()
        destination.unlink(missing_ok=True)
        raise MigrationError("Não foi possível exportar a base para o formato criptografado.") from exc
    connection.close()
    _chmod_private(destination)
    _fsync_file(destination)


def migrate_plaintext(path: Path, key: DatabaseKey) -> MigrationResult:
    """Migra uma base plaintext com backup, fingerprint, export e troca atômica. Nunca apaga o original antes da
    base criptografada estar verificada."""
    _ensure_no_running_app(path)
    if not is_plaintext(path):
        raise MigrationError("A base não está em texto claro; a migração não é necessária.")
    if path.stat().st_size == 0:
        raise MigrationError("A base está vazia.")
    if shutil.disk_usage(path.parent).free < path.stat().st_size * 2 + 16 * 1024 * 1024:
        raise MigrationError("Não há espaço em disco suficiente para migrar a base com segurança.")

    with _file_lock(path.parent / "db-migration.lock"):
        # Se uma execução anterior deixou estado, tenta recuperar antes de começar outra.
        _recover(path, key)
        source = sqlite3.connect(path, timeout=5)
        try:
            source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            source.commit()
        finally:
            source.close()
        for suffix in ("-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

        legacy = path.with_name(f"{path.name}.pre-encryption-{_now_stamp()}")
        counter = 1
        while legacy.exists():
            legacy = path.with_name(f"{path.name}.pre-encryption-{_now_stamp()}-{counter}")
            counter += 1
        temporary = path.with_name(f"{path.name}.encrypted.tmp")
        temporary.unlink(missing_ok=True)

        source_connection = sqlite3.connect(path, timeout=5)
        try:
            source_connection.execute("PRAGMA trusted_schema = OFF")
            source_fingerprint = fingerprint(source_connection)
        finally:
            source_connection.close()

        try:
            # O estado precisa existir antes do rename: se o processo morrer entre o rename e o próximo passo,
            # a próxima inicialização encontra a cópia plaintext e devolve o arquivo oficial.
            _write_state(path, {
                "state": "preparing", "legacy": str(legacy), "temporary": str(temporary),
                "fingerprint": source_fingerprint, "profile": CRYPTO_PROFILE,
            })
            _move_no_overwrite(path, legacy)
            _chmod_private(legacy)
            _write_state(path, {
                "state": "exporting", "legacy": str(legacy), "temporary": str(temporary),
                "fingerprint": source_fingerprint, "profile": CRYPTO_PROFILE,
            })
            encrypt_copy(legacy, temporary, key)
            encrypted = connect(temporary, key)
            try:
                problems = encrypted.execute("PRAGMA cipher_integrity_check").fetchall()
                integrity = encrypted.execute("PRAGMA integrity_check").fetchone()[0]
                if problems or integrity != "ok" or fingerprint(encrypted) != source_fingerprint:
                    raise MigrationError("A base criptografada não confere com a original.")
            finally:
                encrypted.close()
            _write_state(path, {
                "state": "exported", "legacy": str(legacy), "temporary": str(temporary),
                "fingerprint": source_fingerprint, "profile": CRYPTO_PROFILE,
            })
            _move_no_overwrite(temporary, path)
            _write_state(path, {
                "state": "swapped", "legacy": str(legacy),
                "fingerprint": source_fingerprint, "profile": CRYPTO_PROFILE,
            })
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if not path.exists() and legacy.exists():
                try:
                    _move_no_overwrite(legacy, path)
                except OSError:
                    pass
            _write_state(path, {
                "state": "failed", "legacy": str(legacy) if legacy.exists() else "",
                "error": str(exc), "profile": CRYPTO_PROFILE,
            })
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError("A migração da base falhou; os dados originais foram preservados.") from exc

        return MigrationResult(database=path, legacy=legacy, migrated=True)


def _recover(path: Path, key: DatabaseKey) -> None:
    """Completa ou desfaz uma migração interrompida antes de abrir a base."""
    state = _read_state(path)
    if not state:
        return
    legacy = Path(state["legacy"]) if state.get("legacy") else None
    temporary = Path(state["temporary"]) if state.get("temporary") else None
    if temporary:
        temporary.unlink(missing_ok=True)
    if path.exists():
        if is_plaintext(path):
            # A troca não chegou a acontecer; o caminho oficial ainda é o original.
            _remove_state(path)
            return
        # A base oficial está criptografada. Se houver uma cópia plaintext, ela já cumpriu o papel de rollback.
        try:
            verify_encrypted(path, key, full=True)
        except DatabaseCryptoError:
            if legacy and legacy.exists():
                raise MigrationError(
                    "A base criptografada não abre e existe uma cópia plaintext de segurança. "
                    f"Feche o app e recupere manualmente: {legacy}"
                )
            raise
        if legacy:
            legacy.unlink(missing_ok=True)
        _remove_state(path)
        return
    if legacy and legacy.exists():
        _move_no_overwrite(legacy, path)
    _remove_state(path)


def prepare_database(path: Path) -> tuple[DatabaseKey, MigrationResult | None]:
    """Prepara uma base para uso: gera/obtém a chave, migra plaintext uma vez e valida a chave."""
    resolved = path.resolve()
    with _local_lock:
        encrypted = resolved.exists() and resolved.stat().st_size > 0 and not is_plaintext(resolved)
        key = get_or_create_key(resolved, create=not encrypted)
        if resolved in _ready:
            return key, _pending.get(resolved)
        _recover(resolved, key)
        result = None
        if resolved.exists() and resolved.stat().st_size:
            if is_plaintext(resolved):
                result = migrate_plaintext(resolved, key)
            else:
                verify_encrypted(resolved, key)
        _ready.add(resolved)
        if result is not None and result.legacy is not None:
            _pending[resolved] = result
        return key, result


def finalize_pending(path: Path | None = None) -> None:
    """Depois que o app subiu, a cópia plaintext da migração já pode sair (a base criptografada foi verificada)."""
    with _local_lock:
        targets = [path.resolve()] if path else list(_pending)
        for target in targets:
            result = _pending.pop(target, None)
            if result and result.legacy:
                result.legacy.unlink(missing_ok=True)
                _remove_state(result.database)
        if path:
            _ready.discard(path.resolve())


def rollback_pending(path: Path | None = None) -> None:
    """Desfaz a migração de uma inicialização que não chegou a subir, deixando o plaintext para o vigia antigo."""
    with _local_lock:
        targets = [path.resolve()] if path else list(_pending)
        for target in targets:
            result = _pending.pop(target, None)
            if result is None or result.legacy is None or not result.legacy.exists():
                continue
            failed = target.with_name(f"{target.name}.encrypted-failed-{_now_stamp()}")
            try:
                if target.exists():
                    _move_no_overwrite(target, failed)
                _move_no_overwrite(result.legacy, target)
                _remove_state(target)
            except OSError:
                # Se não deu para voltar, deixa o estado para a próxima inicialização recuperar.
                _pending[target] = result
                raise
            _ready.discard(target)


def invalidate(path: Path) -> None:
    with _local_lock:
        resolved = path.resolve()
        _ready.discard(resolved)
        result = _pending.pop(resolved, None)
        if result and result.legacy:
            try:
                result.legacy.unlink(missing_ok=True)
                _remove_state(result.database)
            except OSError:
                pass


def encrypt_legacy_backups(folder: Path, key: DatabaseKey, skip: set[Path] | None = None) -> dict[str, list[str]]:
    """Criptografa backups plaintext antigos, um a um, com verificação antes de substituir.

    Um backup que falhar fica como está. O caminho em `skip` (normalmente o backup de uma atualização em
    andamento) também fica como está até o app confirmar que a versão nova subiu.
    """
    skip = {p.resolve() for p in (skip or set())}
    changed: list[str] = []
    failed: list[str] = []
    ignored: list[str] = []
    if not folder.is_dir():
        return {"criptografados": changed, "falharam": failed, "ignorados": ignored}
    for path in sorted(folder.glob("*.sqlite3")):
        if path.resolve() in skip or not is_plaintext(path):
            ignored.append(str(path))
            continue
        temporary = path.with_name(path.name + ".encrypted.tmp")
        temporary.unlink(missing_ok=True)
        source = sqlite3.connect(path, timeout=5)
        try:
            source.execute("PRAGMA trusted_schema = OFF")
            expected = fingerprint(source)
        except sqlite3.DatabaseError:
            ignored.append(str(path))
            continue
        finally:
            source.close()
        try:
            encrypt_copy(path, temporary, key)
            encrypted = connect(temporary, key)
            try:
                problems = encrypted.execute("PRAGMA cipher_integrity_check").fetchall()
                integrity = encrypted.execute("PRAGMA integrity_check").fetchone()[0]
                if problems or integrity != "ok" or fingerprint(encrypted) != expected:
                    raise DatabaseCryptoError("O backup criptografado não confere com o original.")
            finally:
                encrypted.close()
            temporary.replace(path)
            _chmod_private(path)
            changed.append(str(path))
        except Exception as exc:  # noqa: BLE001 - um backup com problema não pode impedir os outros
            temporary.unlink(missing_ok=True)
            failed.append(f"{path}: {exc}")
    return {"criptografados": changed, "falharam": failed, "ignorados": ignored}


def backup_database(source_path: Path, destination: Path, key: DatabaseKey) -> Path:
    """Copia uma base criptografada para outra base criptografada e confere o fingerprint."""
    destination.unlink(missing_ok=True)
    source = connect(source_path, key)
    target = sqlcipher3.connect(destination)
    target.row_factory = sqlcipher3.Row
    try:
        _pragma_batch(target, key)
        source.backup(target)
        target.commit()
        expected = fingerprint(source)
        if fingerprint(target) != expected:
            raise DatabaseCryptoError("O backup não confere com a base original.")
        problems = target.execute("PRAGMA cipher_integrity_check").fetchall()
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if problems or integrity != "ok":
            raise DatabaseCryptoError("A verificação de autenticação do backup falhou.")
    except Exception:
        target.close()
        source.close()
        destination.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    _chmod_private(destination)
    _fsync_file(destination)
    return destination
