-- Metas de gastos (orçamento mensal) por grupo de categorias.
-- categories: lista JSON de categorias; ["*"] = todos os gastos (meta de gasto total do mês).
CREATE TABLE IF NOT EXISTS budget (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    categories TEXT NOT NULL,
    monthly_limit_cents INTEGER NOT NULL CHECK (monthly_limit_cents > 0),
    alert_pct REAL NOT NULL DEFAULT 0.8 CHECK (alert_pct > 0 AND alert_pct <= 1),
    author TEXT NOT NULL DEFAULT 'usuario',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Recomendações orçamentárias do agente: um conjunto por mês analisado e autor.
CREATE TABLE IF NOT EXISTS budget_advice_set (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    body_md TEXT,
    expected_monthly_savings_cents INTEGER,
    author TEXT NOT NULL DEFAULT 'agente',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (period, author)
);

-- Itens: criar/ajustar/remover uma meta ou uma ação de economia (sem meta).
CREATE TABLE IF NOT EXISTS budget_advice_item (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES budget_advice_set(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('criar', 'ajustar', 'manter', 'remover', 'economizar')),
    budget_name TEXT,
    categories TEXT,
    current_limit_cents INTEGER,
    suggested_limit_cents INTEGER,
    expected_monthly_savings_cents INTEGER,
    priority INTEGER CHECK (priority IS NULL OR priority BETWEEN 1 AND 3),
    rationale TEXT,
    applied_at TEXT,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_budget_advice_item_set ON budget_advice_item (set_id, position);
