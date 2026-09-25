-- Categoria escolhida pelo usuário/agente: sobrevive às sincronizações, que regravam `category`.
ALTER TABLE cash_transaction ADD COLUMN user_category TEXT;

-- Regras de categorização do usuário/agente: "descrição contém X" → categoria. Valem antes das regras internas.
CREATE TABLE IF NOT EXISTS category_rule (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    account_name TEXT,
    author TEXT NOT NULL DEFAULT 'usuario',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (pattern, account_name)
);

-- Empresa por trás do ticker (CVM) e perfil de mercado.
CREATE TABLE IF NOT EXISTS company_profile (
    instrument_id INTEGER PRIMARY KEY REFERENCES instrument(id),
    cnpj TEXT,
    cvm_code TEXT,
    company_name TEXT,
    sector TEXT,
    industry TEXT,
    summary TEXT,
    is_financial INTEGER NOT NULL DEFAULT 0,
    market_cap_cents INTEGER,
    shares_outstanding INTEGER,
    price_earnings REAL,
    market_updated_at TEXT,
    statements_updated_at TEXT
);

-- Métricas em formato longo, para qualquer origem (CVM, brapi, agente de IA):
-- period_type 'Q' = trimestre isolado, 'TTM' = 12 meses, 'SNAPSHOT' = posição na data (balanço/mercado).
CREATE TABLE IF NOT EXISTS fundamental_metric (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    period_end TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('Q', 'TTM', 'SNAPSHOT')),
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (instrument_id, period_end, period_type, metric, source)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_metric_lookup
    ON fundamental_metric (instrument_id, metric, period_end DESC);

-- Documentos oficiais entregues à CVM (ITR/DFP), com link para leitura.
CREATE TABLE IF NOT EXISTS company_filing (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    period_end TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    version INTEGER,
    received_at TEXT,
    link TEXT,
    UNIQUE (instrument_id, period_end, doc_type)
);

-- Relatórios de análise (agente de IA, regras automáticas ou anotações do usuário).
CREATE TABLE IF NOT EXISTS analysis_report (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instrument(id),
    period TEXT,
    kind TEXT NOT NULL DEFAULT 'trimestral',
    title TEXT NOT NULL,
    summary TEXT,
    body_md TEXT,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('barata', 'justa', 'cara')),
    score REAL,
    fair_price_cents INTEGER,
    author TEXT NOT NULL DEFAULT 'agente',
    model TEXT,
    sources TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (instrument_id, period, kind, author)
);

-- Avisos: fundamento piorando, preço barato/caro, dado faltando etc.
CREATE TABLE IF NOT EXISTS fundamental_alert (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instrument(id),
    code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'atencao', 'critico', 'positivo')),
    message TEXT NOT NULL,
    metric TEXT,
    value REAL,
    threshold REAL,
    period_end TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    UNIQUE (instrument_id, code, period_end, source)
);
