-- Gestão a dois (ou mais): pessoas da casa, conexões Pluggy com credenciais próprias e titular de cada conta.

-- Titulares. O 1 é o dono do app; contas sem titular (member_id NULL) são dele.
-- document_hash: HMAC do CPF com um sal local (app_setting 'household_salt'); o CPF em si não é guardado.
CREATE TABLE IF NOT EXISTS household_member (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    document_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO household_member(id, name)
VALUES (1, COALESCE((SELECT NULLIF(TRIM(value), '') FROM app_setting WHERE key = 'display_name'), 'Eu'));

-- Cada conexão tem Client ID e Secret próprios no cofre. A 1 usa os nomes antigos
-- (pluggy_client_id, pluggy_client_secret); as demais, 'pluggy_client_id:<id>'.
CREATE TABLE IF NOT EXISTS pluggy_connection (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO pluggy_connection(id, label) VALUES (1, 'Principal');

CREATE TABLE IF NOT EXISTS pluggy_item (
    item_id TEXT PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES pluggy_connection(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Os Item IDs da configuração antiga ("id1, id2") vão para a conexão 1, com o dono do app como titular.
WITH RECURSIVE split(rest, item) AS (
    SELECT REPLACE((SELECT value FROM app_setting WHERE key = 'pluggy_item_ids'), ' ', '') || ',', NULL
    UNION ALL
    SELECT SUBSTR(rest, INSTR(rest, ',') + 1), SUBSTR(rest, 1, INSTR(rest, ',') - 1) FROM split WHERE rest <> ''
)
INSERT OR IGNORE INTO pluggy_item(item_id, connection_id, member_id)
SELECT LOWER(item), 1, 1 FROM split WHERE item IS NOT NULL AND item <> '';

DELETE FROM app_setting WHERE key IN ('pluggy_item_ids', 'pluggy_item_id');

ALTER TABLE financial_account ADD COLUMN member_id INTEGER REFERENCES household_member(id);
