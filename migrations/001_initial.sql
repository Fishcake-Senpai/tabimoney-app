CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_run (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    external_updated_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    records_read INTEGER NOT NULL DEFAULT 0,
    records_written INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS financial_account (
    id INTEGER PRIMARY KEY,
    institution TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'BRL',
    provider TEXT NOT NULL,
    external_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, external_key)
);

CREATE TABLE IF NOT EXISTS account_balance_snapshot (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    sync_run_id INTEGER REFERENCES sync_run(id),
    source TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    balance_cents INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, source, as_of_date)
);

CREATE TABLE IF NOT EXISTS cash_transaction (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    sync_run_id INTEGER REFERENCES sync_run(id),
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'PENDING', 'UNKNOWN')),
    currency TEXT NOT NULL DEFAULT 'BRL',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS instrument (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'BRL',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investment_event (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    sync_run_id INTEGER REFERENCES sync_run(id),
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    quantity_micros INTEGER NOT NULL DEFAULT 0,
    amount_cents INTEGER,
    unit_price_cents INTEGER,
    description TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS position_snapshot (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES financial_account(id),
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    sync_run_id INTEGER REFERENCES sync_run(id),
    source TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    quantity_micros INTEGER NOT NULL,
    reported_value_cents INTEGER,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, instrument_id, source, as_of_date)
);

CREATE TABLE IF NOT EXISTS daily_quote (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    trade_date TEXT NOT NULL,
    close_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'BRL',
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (instrument_id, trade_date, provider)
);

CREATE TABLE IF NOT EXISTS reconciliation_note (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cash_transaction_account_date
    ON cash_transaction (account_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_investment_event_account_instrument_date
    ON investment_event (account_id, instrument_id, event_date);
CREATE INDEX IF NOT EXISTS idx_position_snapshot_asof
    ON position_snapshot (account_id, instrument_id, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_quote_date
    ON daily_quote (instrument_id, trade_date DESC);

CREATE VIEW IF NOT EXISTS v_latest_position_per_account AS
WITH ranked AS (
    SELECT
        ps.*,
        ROW_NUMBER() OVER (
            PARTITION BY ps.account_id, ps.instrument_id
            ORDER BY ps.as_of_date DESC, ps.imported_at DESC, ps.id DESC
        ) AS row_num
    FROM position_snapshot ps
)
SELECT
    account_id, instrument_id, source, as_of_date,
    quantity_micros, reported_value_cents, sync_run_id
FROM ranked
WHERE row_num = 1;

CREATE VIEW IF NOT EXISTS v_portfolio_positions AS
WITH ranked_sources AS (
    SELECT
        lp.*,
        a.account_name,
        a.provider,
        ROW_NUMBER() OVER (
            PARTITION BY a.account_name, lp.instrument_id
            ORDER BY lp.as_of_date DESC,
                     CASE WHEN a.provider = 'pluggy' THEN 0 ELSE 1 END,
                     lp.sync_run_id DESC
        ) AS source_rank
    FROM v_latest_position_per_account lp
    JOIN financial_account a ON a.id = lp.account_id
)
SELECT
    i.id AS instrument_id,
    i.ticker,
    i.name,
    i.asset_class,
    i.currency,
    SUM(lp.quantity_micros) AS quantity_micros,
    MIN(lp.as_of_date) AS oldest_position_date,
    MAX(lp.as_of_date) AS latest_position_date,
    COUNT(*) AS account_count,
    GROUP_CONCAT(DISTINCT lp.source) AS position_sources
FROM ranked_sources lp
JOIN instrument i ON i.id = lp.instrument_id
WHERE lp.source_rank = 1
GROUP BY i.id, i.ticker, i.name, i.asset_class, i.currency
HAVING SUM(lp.quantity_micros) <> 0;

CREATE VIEW IF NOT EXISTS v_asset_valuation AS
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
        LAG(close_cents) OVER (
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

CREATE VIEW IF NOT EXISTS v_portfolio_totals AS
SELECT
    COALESCE(SUM(market_value_cents), 0) AS market_value_cents,
    COALESCE(SUM(daily_price_change_cents), 0) AS daily_price_change_cents,
    COUNT(*) AS position_count,
    COALESCE(SUM(CASE WHEN quote_status = 'MISSING' THEN 1 ELSE 0 END), 0) AS missing_quote_count,
    COALESCE(SUM(CASE WHEN quote_status = 'STALE' THEN 1 ELSE 0 END), 0) AS stale_quote_count,
    COALESCE(SUM(CASE WHEN daily_price_change_cents IS NOT NULL THEN 1 ELSE 0 END), 0) AS daily_change_available_count
FROM v_asset_valuation;

CREATE VIEW IF NOT EXISTS v_bank_latest_balances AS
WITH per_account AS (
    SELECT
        abs.account_id,
        abs.as_of_date,
        abs.balance_cents,
        abs.source AS data_source,
        abs.imported_at,
        ROW_NUMBER() OVER (
            PARTITION BY abs.account_id
            ORDER BY abs.as_of_date DESC, abs.imported_at DESC, abs.id DESC
        ) AS row_num
    FROM account_balance_snapshot abs
), account_choices AS (
    SELECT
        a.id AS account_id,
        a.account_name,
        a.account_type,
        p.as_of_date,
        p.balance_cents,
        p.data_source,
        ROW_NUMBER() OVER (
            PARTITION BY a.account_name, a.account_type
            ORDER BY p.as_of_date DESC,
                     CASE WHEN a.provider = 'pluggy' THEN 0 ELSE 1 END,
                     p.imported_at DESC,
                     a.id DESC
        ) AS source_rank
    FROM per_account p
    JOIN financial_account a ON a.id = p.account_id
    WHERE p.row_num = 1 AND a.account_type = 'BANK'
)
SELECT
    account_id,
    account_name,
    account_type,
    as_of_date,
    balance_cents,
    data_source
FROM account_choices
WHERE source_rank = 1;

CREATE VIEW IF NOT EXISTS v_personal_totals AS
WITH cash AS (
    SELECT COALESCE(SUM(balance_cents), 0) AS cash_cents,
           COUNT(*) AS bank_account_count
    FROM v_bank_latest_balances
), portfolio AS (
    SELECT market_value_cents, daily_price_change_cents, position_count,
           missing_quote_count, stale_quote_count, daily_change_available_count
    FROM v_portfolio_totals
)
SELECT
    cash.cash_cents,
    portfolio.market_value_cents,
    CASE WHEN portfolio.missing_quote_count > 0 OR (cash.bank_account_count = 0 AND portfolio.position_count = 0)
         THEN NULL ELSE cash.cash_cents + portfolio.market_value_cents END AS tracked_net_worth_cents,
    CASE WHEN portfolio.daily_change_available_count = 0 THEN NULL
         ELSE portfolio.daily_price_change_cents END AS daily_price_change_cents,
    portfolio.daily_change_available_count,
    portfolio.position_count,
    portfolio.missing_quote_count,
    portfolio.stale_quote_count,
    cash.bank_account_count
FROM cash CROSS JOIN portfolio;

CREATE VIEW IF NOT EXISTS v_position_reconciliation AS
WITH ranked_openings AS (
    SELECT
        ie.account_id,
        ie.instrument_id,
        ie.event_date,
        ie.quantity_micros,
        ROW_NUMBER() OVER (
            PARTITION BY ie.account_id, ie.instrument_id
            ORDER BY ie.event_date DESC, ie.id DESC
        ) AS row_num
    FROM investment_event ie
    WHERE ie.event_type = 'OPENING'
), baselines AS (
    SELECT account_id, instrument_id, event_date, quantity_micros
    FROM ranked_openings
    WHERE row_num = 1
), event_totals AS (
    SELECT
        b.account_id,
        b.instrument_id,
        b.quantity_micros + COALESCE(SUM(CASE
            WHEN e.event_type IN ('BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT')
            THEN e.quantity_micros ELSE 0
        END), 0) AS calculated_quantity_micros,
        1 AS has_opening,
        COUNT(e.id) + 1 AS event_count,
        COALESCE(SUM(CASE
            WHEN (e.event_type IN ('BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT') AND e.quantity_micros = 0)
              OR (e.quantity_micros <> 0 AND e.event_type NOT IN ('BUY', 'SELL', 'TRANSFER_IN', 'TRANSFER_OUT'))
            THEN 1 ELSE 0
        END), 0) AS unmodeled_event_count
    FROM baselines b
    LEFT JOIN investment_event e
        ON e.account_id = b.account_id
       AND e.instrument_id = b.instrument_id
       AND e.event_date > b.event_date
       AND e.event_type <> 'OPENING'
    GROUP BY b.account_id, b.instrument_id, b.event_date, b.quantity_micros
), ranked_sources AS (
    SELECT
        lp.*,
        a.account_name,
        ROW_NUMBER() OVER (
            PARTITION BY a.account_name, lp.instrument_id
            ORDER BY lp.as_of_date DESC,
                     CASE WHEN a.provider = 'pluggy' THEN 0 ELSE 1 END,
                     lp.sync_run_id DESC
        ) AS source_rank
    FROM v_latest_position_per_account lp
    JOIN financial_account a ON a.id = lp.account_id
)
SELECT
    lp.account_name,
    i.ticker,
    lp.as_of_date,
    lp.quantity_micros AS reported_quantity_micros,
    et.calculated_quantity_micros,
    CASE WHEN et.has_opening = 1 AND et.unmodeled_event_count = 0
         THEN lp.quantity_micros - et.calculated_quantity_micros ELSE NULL END AS difference_micros,
    CASE WHEN et.has_opening IS NULL OR et.has_opening = 0 THEN 'INSUFFICIENT_HISTORY'
         WHEN et.unmodeled_event_count > 0 THEN 'INSUFFICIENT_HISTORY'
         WHEN ABS(lp.quantity_micros - et.calculated_quantity_micros) <= 1 THEN 'OK'
         ELSE 'DIVERGENT'
    END AS status,
    COALESCE(et.event_count, 0) AS event_count
FROM ranked_sources lp
JOIN instrument i ON i.id = lp.instrument_id
LEFT JOIN event_totals et ON et.account_id = lp.account_id AND et.instrument_id = lp.instrument_id
WHERE lp.source_rank = 1;

CREATE VIEW IF NOT EXISTS v_bank_balance_reconciliation AS
WITH latest_by_account AS (
    SELECT
        abs.account_id,
        abs.as_of_date,
        abs.balance_cents,
        abs.source AS data_source,
        abs.imported_at,
        ROW_NUMBER() OVER (
            PARTITION BY abs.account_id
            ORDER BY abs.as_of_date DESC, abs.imported_at DESC, abs.id DESC
        ) AS account_row_num
    FROM account_balance_snapshot abs
), alias_ranked AS (
    SELECT
        l.account_id,
        l.as_of_date,
        l.balance_cents,
        l.data_source,
        l.imported_at,
        a.account_name,
        a.account_type,
        ROW_NUMBER() OVER (
            PARTITION BY a.account_name, a.account_type
            ORDER BY l.as_of_date DESC,
                     CASE WHEN a.provider = 'pluggy' THEN 0 ELSE 1 END,
                     l.imported_at DESC,
                     a.id DESC
        ) AS alias_row_num
    FROM latest_by_account l
    JOIN financial_account a ON a.id = l.account_id
    WHERE l.account_row_num = 1 AND a.account_type = 'BANK'
), winning_accounts AS (
    SELECT account_id, account_name, data_source
    FROM alias_ranked
    WHERE alias_row_num = 1
), ranked AS (
    SELECT
        abs.*,
        ROW_NUMBER() OVER (
            PARTITION BY abs.account_id
            ORDER BY abs.as_of_date DESC, abs.imported_at DESC, abs.id DESC
        ) AS row_num
    FROM account_balance_snapshot abs
    JOIN winning_accounts w ON w.account_id = abs.account_id
), latest AS (
    SELECT * FROM ranked WHERE row_num = 1
), previous AS (
    SELECT * FROM ranked WHERE row_num = 2
), movement AS (
    SELECT
        l.account_id,
        COALESCE(SUM(ct.amount_cents), 0) AS movement_cents
    FROM latest l
    LEFT JOIN previous p ON p.account_id = l.account_id
    LEFT JOIN cash_transaction ct
        ON ct.account_id = l.account_id
       AND ct.status = 'POSTED'
       AND ct.transaction_date > p.as_of_date
       AND ct.transaction_date <= l.as_of_date
    GROUP BY l.account_id
)
SELECT
    w.account_name,
    l.as_of_date,
    w.data_source,
    l.balance_cents AS reported_balance_cents,
    CASE WHEN p.id IS NULL THEN NULL ELSE p.balance_cents + m.movement_cents END AS calculated_balance_cents,
    CASE WHEN p.id IS NULL THEN NULL ELSE l.balance_cents - p.balance_cents - m.movement_cents END AS difference_cents,
    CASE WHEN p.id IS NULL THEN 'INSUFFICIENT_HISTORY'
         WHEN ABS(l.balance_cents - p.balance_cents - m.movement_cents) <= 1 THEN 'OK'
         ELSE 'DIVERGENT'
    END AS status
FROM latest l
JOIN winning_accounts w ON w.account_id = l.account_id
LEFT JOIN previous p ON p.account_id = l.account_id
LEFT JOIN movement m ON m.account_id = l.account_id;
