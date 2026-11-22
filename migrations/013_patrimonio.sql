-- Gestão de patrimônio físico (imóveis, veículos e outros bens) com histórico de avaliações da IA.

CREATE TABLE IF NOT EXISTS physical_asset (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    asset_type TEXT NOT NULL CHECK (asset_type IN ('imovel', 'veiculo', 'outro')),
    subtype TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'vendido')),
    acquisition_date TEXT,
    acquisition_cents INTEGER NOT NULL DEFAULT 0,
    current_value_cents INTEGER NOT NULL DEFAULT 0,
    valuation_method TEXT NOT NULL DEFAULT 'manual' CHECK (valuation_method IN ('manual', 'regra', 'ia')),
    growth_rate_bps INTEGER NOT NULL DEFAULT 0,
    growth_period TEXT NOT NULL DEFAULT 'anual' CHECK (growth_period IN ('mensal', 'anual')),
    growth_start_date TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    estimated_annual_tax_cents INTEGER NOT NULL DEFAULT 0,
    estimated_annual_insurance_cents INTEGER NOT NULL DEFAULT 0,
    estimated_monthly_rent_cents INTEGER NOT NULL DEFAULT 0,
    estimated_annual_maintenance_cents INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_physical_asset_active
    ON physical_asset (status, deleted_at, member_id);

CREATE TABLE IF NOT EXISTS asset_valuation (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES physical_asset(id) ON DELETE CASCADE,
    evaluated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'regra', 'ia')),
    value_cents INTEGER NOT NULL,
    value_low_cents INTEGER,
    value_high_cents INTEGER,
    confidence TEXT CHECK (confidence IS NULL OR confidence IN ('alta', 'media', 'baixa', 'insuficiente')),
    comparables_json TEXT NOT NULL DEFAULT '[]',
    kpis_json TEXT NOT NULL DEFAULT '{}',
    sources_json TEXT NOT NULL DEFAULT '[]',
    report_md TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_asset_valuation_asset_date
    ON asset_valuation (asset_id, evaluated_at DESC, id DESC);
