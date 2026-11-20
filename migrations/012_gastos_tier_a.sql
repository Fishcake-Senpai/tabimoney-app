-- Fundação de Gastos (Tier A): lançamentos manuais e editáveis, ignorar/fora do resultado,
-- desfazer importação, pendências dispensadas, contas fixas com baixa automática e comprovantes.

-- Contas fixas (recorrências): o status (pago, pendente, atrasado) é derivado na leitura.
CREATE TABLE IF NOT EXISTS recurring_transaction (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category TEXT,
    frequency TEXT NOT NULL CHECK (frequency IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')),
    day_of_month INTEGER CHECK (day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31),
    start_date TEXT NOT NULL,
    end_date TEXT,
    adjust_business_day INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    match_pattern TEXT,
    note TEXT,
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_recurring_active
    ON recurring_transaction (active, deleted_at);

-- Campos extras em cash_transaction: nota, ignorado, fora do resultado, exclusão reversível e vínculo com conta fixa.
ALTER TABLE cash_transaction ADD COLUMN note TEXT;
ALTER TABLE cash_transaction ADD COLUMN is_ignored INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cash_transaction ADD COLUMN exclude_from_pnl INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cash_transaction ADD COLUMN deleted_at TEXT;
ALTER TABLE cash_transaction ADD COLUMN recurring_id INTEGER REFERENCES recurring_transaction(id);
ALTER TABLE cash_transaction ADD COLUMN recurring_due_date TEXT;

CREATE INDEX IF NOT EXISTS idx_cash_transaction_recurring
    ON cash_transaction (recurring_id, recurring_due_date);

-- Categoria pode ser marcada como fora do resultado (conta no saldo, sai de receitas e despesas).
ALTER TABLE category ADD COLUMN exclude_from_pnl INTEGER NOT NULL DEFAULT 0;

-- Importação desfeita fica registrada no histórico.
ALTER TABLE sync_run ADD COLUMN undone_at TEXT;

-- Pendências dispensadas: recusa explícita nunca volta (expires_at NULL).
CREATE TABLE IF NOT EXISTS dismissed_pending (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('transfer_orphan', 'position', 'bank')),
    entity_key TEXT NOT NULL,
    dismissed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    UNIQUE (kind, entity_key)
);

-- Comprovantes anexados aos lançamentos (arquivos locais em <data_dir>/attachments/).
CREATE TABLE IF NOT EXISTS transaction_attachment (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES cash_transaction(id),
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_transaction_attachment_tx
    ON transaction_attachment (transaction_id, deleted_at);
