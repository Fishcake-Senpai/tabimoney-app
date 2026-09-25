-- Categoria e referência de fatura nas movimentações; limites do cartão na conta.
ALTER TABLE cash_transaction ADD COLUMN category TEXT;
ALTER TABLE cash_transaction ADD COLUMN statement_ref TEXT;
ALTER TABLE financial_account ADD COLUMN credit_limit_cents INTEGER;
ALTER TABLE financial_account ADD COLUMN available_limit_cents INTEGER;

-- Renda fixa e demais produtos sem ticker B3 (CDB, RDB, Caixinhas, LCI/LCA, Tesouro, fundos).
CREATE TABLE IF NOT EXISTS fixed_income_snapshot (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    sync_run_id INTEGER REFERENCES sync_run(id),
    source TEXT NOT NULL,
    product_key TEXT NOT NULL,
    product_type TEXT NOT NULL,
    name TEXT NOT NULL,
    issuer TEXT,
    indexer TEXT,
    rate TEXT,
    maturity_date TEXT,
    as_of_date TEXT NOT NULL,
    invested_cents INTEGER,
    gross_value_cents INTEGER NOT NULL,
    net_value_cents INTEGER,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_key, source, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_fixed_income_product_date
    ON fixed_income_snapshot (product_key, as_of_date DESC);

-- Séries de referência: IBOV (pontos) e CDI (taxa diária em %).
CREATE TABLE IF NOT EXISTS benchmark_quote (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    value REAL NOT NULL,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, trade_date)
);

-- Correção: a variação diária usava LAG numa janela decrescente, então o fechamento
-- anterior do pregão mais recente era sempre NULL. LEAD pega o pregão anterior.
DROP VIEW IF EXISTS v_asset_valuation;
CREATE VIEW v_asset_valuation AS
WITH selected_quote_rows AS (
    SELECT
        dq.id,
        dq.instrument_id,
        dq.trade_date,
        dq.close_cents,
        dq.provider,
        ROW_NUMBER() OVER (
            PARTITION BY dq.instrument_id, dq.trade_date
            ORDER BY CASE WHEN dq.provider = 'manual' THEN 0 ELSE 1 END, dq.fetched_at DESC, dq.id DESC
        ) AS source_rank
    FROM daily_quote dq
), quote_rows AS (
    SELECT
        id,
        instrument_id,
        trade_date,
        close_cents,
        provider,
        LEAD(close_cents) OVER (
            PARTITION BY instrument_id
            ORDER BY trade_date DESC, id DESC
        ) AS previous_close_cents,
        ROW_NUMBER() OVER (
            PARTITION BY instrument_id
            ORDER BY trade_date DESC, id DESC
        ) AS row_num
    FROM selected_quote_rows dq
    WHERE source_rank = 1
)
SELECT
    p.instrument_id,
    p.ticker,
    p.name,
    p.asset_class,
    p.currency,
    p.quantity_micros,
    q.trade_date AS quote_date,
    q.provider AS quote_source,
    q.close_cents,
    q.previous_close_cents,
    CASE WHEN q.close_cents IS NULL THEN NULL
         ELSE CAST((p.quantity_micros * q.close_cents + 500000) / 1000000 AS INTEGER)
    END AS market_value_cents,
    CASE WHEN q.close_cents IS NULL OR q.previous_close_cents IS NULL THEN NULL
         ELSE CAST(ROUND((p.quantity_micros * (q.close_cents - q.previous_close_cents)) / 1000000.0, 0) AS INTEGER)
    END AS daily_price_change_cents,
    CASE WHEN q.close_cents IS NULL OR q.previous_close_cents IS NULL OR q.previous_close_cents = 0 THEN NULL
         ELSE ROUND(100.0 * (q.close_cents - q.previous_close_cents) / q.previous_close_cents, 4)
    END AS daily_price_change_pct,
    CASE WHEN q.trade_date IS NULL THEN 'MISSING'
         WHEN julianday('now') - julianday(q.trade_date) > 4 THEN 'STALE'
         ELSE 'OK'
    END AS quote_status
FROM v_portfolio_positions p
LEFT JOIN quote_rows q ON q.instrument_id = p.instrument_id AND q.row_num = 1;
