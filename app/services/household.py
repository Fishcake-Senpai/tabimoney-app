"""Titulares (pessoas da casa) e conexões do Meu Pluggy.

Um casal que faz a gestão junto conecta os bancos de cada um. O app precisa saber de quem é cada conta:
- para não misturar contas iguais de pessoas diferentes (dois "Nubank / NuInvest", dois "Nubank Cartão"). Os
  cálculos juntam as contas pelo nome, então as contas de um titular que não é o dono do app levam o
  sufixo " · Nome";
- para tratar o Pix entre o casal como movimento interno, e não como despesa de um e receita do outro;
- para mostrar a visão da casa ou de uma pessoa só.

O titular 1 é o dono do app e nunca é excluído. Contas sem titular (member_id NULL), como as importadas por
arquivo, são dele. O CPF não é guardado: fica só um HMAC com um sal local, que basta para reconhecer o
titular no pagador ou no recebedor de um Pix.

Cada conexão tem as próprias credenciais no cofre. A conexão 1 usa os nomes das versões anteriores
(pluggy_client_id, pluggy_client_secret) para não pedir as chaves de novo depois da atualização.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any
from uuid import UUID

from app.db import get_setting, rows, set_setting, transaction
from app.services.spending import normalize

PRIMARY_ID = 1
SALT_KEY = "household_salt"
SUFFIX_SEPARATOR = " · "

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.IGNORECASE)


# ---------------------------------------------------------------- CPF

def digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def valid_cpf(value: object) -> bool:
    cpf = digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11 % 10
        if check != int(cpf[size]):
            return False
    return True


def _salt() -> str:
    value = get_setting(SALT_KEY)
    if not value:
        value = secrets.token_hex(16)
        set_setting(SALT_KEY, value)
    return value


def document_key(value: object, salt: str | None = None) -> str:
    """HMAC do documento (só dígitos). Vazio quando não há documento."""
    number = digits(value)
    if not number:
        return ""
    return hmac.new((salt or _salt()).encode(), number.encode(), hashlib.sha256).hexdigest()


class Documents:
    """Reconhece os titulares no pagador e no recebedor de uma movimentação, sem abrir conexões por lançamento."""

    def __init__(self) -> None:
        self.salt = _salt()
        self.by_key = {r["document_hash"]: int(r["id"]) for r in rows(
            "SELECT id, document_hash FROM household_member WHERE document_hash IS NOT NULL"
        )}

    def member_of(self, value: object) -> int | None:
        key = document_key(value, self.salt)
        return self.by_key.get(key) if key else None


# ---------------------------------------------------------------- titulares

def members() -> list[dict[str, Any]]:
    data = rows(
        "SELECT m.id, m.name, m.document_hash IS NOT NULL AS has_document, "
        "(SELECT COUNT(*) FROM pluggy_item i WHERE i.member_id = m.id) AS items, "
        "(SELECT COUNT(*) FROM financial_account a WHERE COALESCE(a.member_id, 1) = m.id) AS accounts "
        "FROM household_member m ORDER BY m.id"
    )
    return [{**dict(r), "has_document": bool(r["has_document"]), "is_primary": r["id"] == PRIMARY_ID} for r in data]


def member(member_id: int | None) -> dict[str, Any] | None:
    if member_id is None:
        return None
    return next((m for m in members() if m["id"] == member_id), None)


def is_shared() -> bool:
    """Mais de um titular: as telas mostram o seletor e a visão da casa."""
    return bool(rows("SELECT 1 FROM household_member WHERE id <> ? LIMIT 1", (PRIMARY_ID,)))


def resolve(value: object) -> int | None:
    """Titular pelo id ou pelo nome (sem caixa nem acento). None = a casa toda."""
    text = " ".join(str(value or "").split())
    if not text or text.casefold() in {"casa", "todos", "*"}:
        return None
    for m in members():
        if text == str(m["id"]) or normalize(text) == normalize(m["name"]):
            return int(m["id"])
    raise ValueError(f"Titular não encontrado: {text}.")


def suffix(member_id: int | None, name: str | None = None) -> str:
    """Sufixo do nome das contas do titular. O dono do app não tem sufixo, e os nomes antigos continuam valendo."""
    if member_id is None or member_id == PRIMARY_ID:
        return ""
    if name is None:
        found = member(member_id)
        name = found["name"] if found else None
    return f"{SUFFIX_SEPARATOR}{name}" if name else ""


def _clean_name(name: str) -> str:
    text = " ".join((name or "").split())
    if not 1 <= len(text) <= 30:
        raise ValueError("O nome do titular precisa ter de 1 a 30 caracteres.")
    if SUFFIX_SEPARATOR.strip() in text:
        raise ValueError("O nome do titular não pode ter o caractere ·.")
    if text.casefold() in {"casa", "todos"}:
        raise ValueError(f"'{text}' é um nome reservado para a visão da casa.")
    return text


def _document_or_none(connection, cpf: str | None, member_id: int | None) -> str | None:
    if not cpf or not digits(cpf):
        return None
    if not valid_cpf(cpf):
        raise ValueError("CPF inválido. Confira os 11 dígitos.")
    key = document_key(cpf)
    other = connection.execute(
        "SELECT name FROM household_member WHERE document_hash = ? AND id IS NOT ?", (key, member_id)
    ).fetchone()
    if other:
        raise ValueError(f"Esse CPF já é de {other['name']}.")
    return key


def add_member(name: str, cpf: str | None = None) -> dict[str, Any]:
    text = _clean_name(name)
    _salt()
    with transaction() as connection:
        if connection.execute("SELECT 1 FROM household_member WHERE name = ?", (text,)).fetchone():
            raise ValueError(f"Já existe um titular chamado {text}.")
        key = _document_or_none(connection, cpf, None)
        cursor = connection.execute("INSERT INTO household_member(name, document_hash) VALUES (?, ?)", (text, key))
        return {"id": int(cursor.lastrowid), "name": text, "has_document": key is not None}


def update_member(member_id: int, name: str | None = None, cpf: str | None = None,
                  remove_document: bool = False) -> dict[str, Any]:
    """Renomeia (e reescreve o sufixo das contas, os % do CDI e as regras por conta) e grava ou apaga o CPF."""
    current = member(member_id)
    if current is None:
        raise ValueError("Titular não encontrado.")
    new_name = _clean_name(name) if name and name.strip() else current["name"]
    _salt()
    with transaction() as connection:
        if new_name != current["name"] and connection.execute(
            "SELECT 1 FROM household_member WHERE name = ? AND id <> ?", (new_name, member_id)
        ).fetchone():
            raise ValueError(f"Já existe um titular chamado {new_name}.")
        key = _document_or_none(connection, cpf, member_id)
        if key:
            connection.execute("UPDATE household_member SET document_hash = ? WHERE id = ?", (key, member_id))
        elif remove_document:
            connection.execute("UPDATE household_member SET document_hash = NULL WHERE id = ?", (member_id,))
        if new_name != current["name"]:
            connection.execute("UPDATE household_member SET name = ? WHERE id = ?", (new_name, member_id))
            if member_id != PRIMARY_ID:
                old, new = suffix(member_id, current["name"]), suffix(member_id, new_name)
                for account in connection.execute(
                    "SELECT id FROM financial_account WHERE member_id = ?", (member_id,)
                ).fetchall():
                    _relabel(connection, int(account["id"]), old, new, member_id)
    if member_id == PRIMARY_ID and new_name != current["name"] and not get_setting("display_name"):
        set_setting("display_name", new_name)
    return member(member_id) or {}


def delete_member(member_id: int) -> None:
    if member_id == PRIMARY_ID:
        raise ValueError("O titular principal não pode ser excluído.")
    found = member(member_id)
    if found is None:
        raise ValueError("Titular não encontrado.")
    if found["items"] or found["accounts"]:
        raise ValueError(
            f"{found['name']} ainda tem contas ou Item IDs. Passe os Item IDs para outro titular ou remova-os antes."
        )
    with transaction() as connection:
        connection.execute("DELETE FROM household_member WHERE id = ?", (member_id,))


def learn_document(member_id: int, document: object) -> bool:
    """Grava o CPF que a Pluggy informou para o item, se o titular ainda não tem um e ninguém mais o usa."""
    if not valid_cpf(document):
        return False
    key = document_key(document)
    with transaction() as connection:
        row = connection.execute("SELECT document_hash FROM household_member WHERE id = ?", (member_id,)).fetchone()
        if row is None or row["document_hash"]:
            return False
        if connection.execute("SELECT 1 FROM household_member WHERE document_hash = ?", (key,)).fetchone():
            return False
        connection.execute("UPDATE household_member SET document_hash = ? WHERE id = ?", (key, member_id))
    return True


def _relabel(connection, account_id: int, old_suffix: str, new_suffix: str, member_id: int) -> None:
    """Troca o sufixo do titular no nome da conta e leva junto o que é gravado pelo nome."""
    row = connection.execute("SELECT account_name FROM financial_account WHERE id = ?", (account_id,)).fetchone()
    old_name = row["account_name"]
    base = old_name[: -len(old_suffix)] if old_suffix and old_name.endswith(old_suffix) else old_name
    new_name = base + new_suffix
    connection.execute(
        "UPDATE financial_account SET account_name = ?, member_id = ? WHERE id = ?",
        (new_name, None if member_id == PRIMARY_ID else member_id, account_id),
    )
    if new_name == old_name:
        return
    connection.execute(
        "UPDATE OR IGNORE app_setting SET key = ? WHERE key = ?", (f"cdi_pct:{new_name}", f"cdi_pct:{old_name}")
    )
    connection.execute(
        "UPDATE OR IGNORE category_rule SET account_name = ? WHERE account_name = ?", (new_name, old_name)
    )


# ---------------------------------------------------------------- conexões e itens

def parse_item_ids(text: str | None) -> tuple[list[str], list[str]]:
    """Extrai Item IDs de qualquer texto colado: vírgula, ponto e vírgula, espaço ou quebra de linha,
    aspas, maiúsculas e até a URL do dashboard. Devolve (ids válidos sem repetição, trechos ignorados)."""
    valid: list[str] = []
    ignored: list[str] = []
    for token in re.split(r"[\s,;|]+", text or ""):
        token = token.strip("\"'`[](){}<>.")
        if not token:
            continue
        found = UUID_PATTERN.findall(token)
        if not found:
            ignored.append(token[:40])
        for value in found:
            normalized = str(UUID(value))
            if normalized not in valid:
                valid.append(normalized)
    return valid, ignored


def secret_names(connection_id: int) -> tuple[str, str]:
    if connection_id == 1:
        return "pluggy_client_id", "pluggy_client_secret"
    return f"pluggy_client_id:{connection_id}", f"pluggy_client_secret:{connection_id}"


def connections() -> list[dict[str, Any]]:
    items = rows(
        "SELECT i.item_id, i.connection_id, i.member_id, m.name AS member_name, "
        "(SELECT a.institution FROM financial_account a WHERE a.provider = 'pluggy' "
        " AND a.external_key LIKE 'item:' || i.item_id || ':%' ORDER BY a.id LIMIT 1) AS institution "
        "FROM pluggy_item i JOIN household_member m ON m.id = i.member_id ORDER BY i.connection_id, i.created_at, i.item_id"
    )
    output = []
    for c in rows("SELECT id, label FROM pluggy_connection ORDER BY id"):
        output.append({
            "id": int(c["id"]), "label": c["label"],
            "items": [dict(i) for i in items if i["connection_id"] == c["id"]],
        })
    return output


def items() -> list[dict[str, Any]]:
    return [dict(r) for r in rows(
        "SELECT i.item_id, i.connection_id, i.member_id, m.name AS member_name "
        "FROM pluggy_item i JOIN household_member m ON m.id = i.member_id ORDER BY i.connection_id, i.created_at, i.item_id"
    )]


def item_ids() -> list[str]:
    return [i["item_id"] for i in items()]


def _clean_label(label: str) -> str:
    text = " ".join((label or "").split())
    if not 1 <= len(text) <= 40:
        raise ValueError("Dê um nome de 1 a 40 caracteres para a conexão.")
    return text


def create_connection(label: str) -> int:
    with transaction() as connection:
        return int(connection.execute("INSERT INTO pluggy_connection(label) VALUES (?)", (_clean_label(label),)).lastrowid)


def rename_connection(connection_id: int, label: str) -> None:
    with transaction() as connection:
        connection.execute("UPDATE pluggy_connection SET label = ? WHERE id = ?", (_clean_label(label), connection_id))


def delete_connection(connection_id: int) -> list[str]:
    """Remove a conexão e os Item IDs dela; contas e histórico já importados ficam. Devolve os segredos a apagar."""
    if connection_id == 1:
        raise ValueError("A conexão principal não pode ser excluída; remova as credenciais ou os Item IDs dela.")
    with transaction() as connection:
        if not connection.execute("SELECT 1 FROM pluggy_connection WHERE id = ?", (connection_id,)).fetchone():
            raise ValueError("Conexão não encontrada.")
        connection.execute("DELETE FROM pluggy_item WHERE connection_id = ?", (connection_id,))
        connection.execute("DELETE FROM pluggy_connection WHERE id = ?", (connection_id,))
    return list(secret_names(connection_id))


def add_items(connection_id: int, text: str, member_id: int = PRIMARY_ID) -> dict[str, Any]:
    """Cadastra os Item IDs colados. Um Item ID que já estava em outra conexão muda para esta, e um que já
    existia passa para o titular escolhido."""
    valid, ignored = parse_item_ids(text)
    if member(member_id) is None:
        raise ValueError("Titular não encontrado.")
    added = moved = 0
    other_member: list[str] = []
    with transaction() as connection:
        if not connection.execute("SELECT 1 FROM pluggy_connection WHERE id = ?", (connection_id,)).fetchone():
            raise ValueError("Conexão não encontrada.")
        for item_id in valid:
            row = connection.execute(
                "SELECT connection_id, member_id FROM pluggy_item WHERE item_id = ?", (item_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO pluggy_item(item_id, connection_id, member_id) VALUES (?, ?, ?)",
                    (item_id, connection_id, member_id),
                )
                added += 1
                continue
            if row["connection_id"] != connection_id:
                connection.execute("UPDATE pluggy_item SET connection_id = ? WHERE item_id = ?", (connection_id, item_id))
                moved += 1
            if row["member_id"] != member_id:
                other_member.append(item_id)
    for item_id in other_member:
        set_item_member(item_id, member_id)
    return {"added": added, "moved": moved, "ignored": ignored, "valid": valid}


def remove_item(item_id: str) -> None:
    """Para de sincronizar o item; as contas e o histórico dele ficam."""
    with transaction() as connection:
        connection.execute("DELETE FROM pluggy_item WHERE item_id = ?", (item_id.strip().lower(),))


def set_item_member(item_id: str, member_id: int) -> int:
    """Troca o titular do item e renomeia agora as contas dele (sem esperar a próxima sincronização)."""
    target = member(member_id)
    if target is None:
        raise ValueError("Titular não encontrado.")
    item_id = item_id.strip().lower()
    names = {m["id"]: m["name"] for m in members()}
    with transaction() as connection:
        if not connection.execute("SELECT 1 FROM pluggy_item WHERE item_id = ?", (item_id,)).fetchone():
            raise ValueError("Item ID não encontrado.")
        connection.execute("UPDATE pluggy_item SET member_id = ? WHERE item_id = ?", (member_id, item_id))
        accounts = connection.execute(
            "SELECT id, COALESCE(member_id, 1) AS member_id FROM financial_account "
            "WHERE provider = 'pluggy' AND external_key LIKE ?", (f"item:{item_id}:%",),
        ).fetchall()
        for account in accounts:
            old = int(account["member_id"])
            _relabel(connection, int(account["id"]), suffix(old, names.get(old)), suffix(member_id, target["name"]),
                     member_id)
        return len(accounts)
