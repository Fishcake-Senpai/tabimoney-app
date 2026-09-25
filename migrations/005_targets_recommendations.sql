-- Exposição geográfica do ativo para as metas (NULL = automática: BDR e ETFs de índice externo são internacionais).
ALTER TABLE instrument ADD COLUMN region TEXT CHECK (region IS NULL OR region IN ('nacional', 'internacional'));

-- Relatórios também sobre renda fixa, previdência ou a carteira toda (sem ticker).
ALTER TABLE analysis_report ADD COLUMN subject TEXT;
ALTER TABLE analysis_report ADD COLUMN subject_type TEXT NOT NULL DEFAULT 'ativo';

-- Recomendações trimestrais do agente: um conjunto por trimestre e autor.
CREATE TABLE IF NOT EXISTS recommendation_set (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    body_md TEXT,
    author TEXT NOT NULL DEFAULT 'agente',
    model TEXT,
    sources TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (period, author)
);

-- Carteiras-modelo sugeridas dentro de um conjunto.
CREATE TABLE IF NOT EXISTS recommendation_portfolio (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES recommendation_set(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    rationale_md TEXT,
    risk_profile TEXT,
    UNIQUE (set_id, name)
);

-- Itens: mudanças na carteira atual (portfolio_id NULL) ou composição de uma carteira-modelo.
CREATE TABLE IF NOT EXISTS recommendation_item (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES recommendation_set(id) ON DELETE CASCADE,
    portfolio_id INTEGER REFERENCES recommendation_portfolio(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('comprar', 'aumentar', 'manter', 'reduzir', 'vender', 'incluir')),
    ticker TEXT,
    name TEXT,
    asset_class TEXT,
    region TEXT,
    target_weight REAL,
    rationale TEXT,
    conviction INTEGER CHECK (conviction IS NULL OR conviction BETWEEN 1 AND 5),
    fair_price_cents INTEGER,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recommendation_item_set ON recommendation_item (set_id, portfolio_id, position);
