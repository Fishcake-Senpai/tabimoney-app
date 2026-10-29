-- Imposto de renda: apuração de ações e fundos na bolsa e estimador do ano.
-- Spec: docs/superpowers/specs/2026-10-19-imposto-de-renda.md. Valores em centavos; nada aqui apaga lançamento.

-- Classe fiscal do ativo (alíquota, isenção de R$ 20 mil e ficha da declaração). NULL: o app deduz da classe e do
-- ticker (app/services/ir/renda_variavel.py, tax_class); ticker 11 sem pista vira pendência.
ALTER TABLE instrument ADD COLUMN tax_class TEXT
    CHECK (tax_class IS NULL OR tax_class IN ('acao', 'unit', 'bdr', 'etf', 'etf_rf', 'fii', 'fiagro', 'outro'));

-- O que o titular informa para a apuração da bolsa (o que as planilhas não trazem):
--   prejuizo_anterior: prejuízo a compensar até 31/12 do ano anterior a `period` (AAAA), por grupo;
--   irrf: IRRF do mês (AAAA-MM) e grupo, da nota ou do informe da corretora;
--   taxa: taxas do mês (AAAA-MM) numa conta (account_name), rateadas pelas operações do mês;
--   darf_pago: DARF do mês (AAAA-MM) pago, com a data;
--   custo_bonificacao: custo por ação (amount_cents) da bonificação do evento ref_id.
-- grupo e account_name usam '' para "não se aplica" (assim o UNIQUE funciona).
CREATE TABLE IF NOT EXISTS ir_rv_info (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    kind TEXT NOT NULL CHECK (kind IN ('prejuizo_anterior', 'irrf', 'taxa', 'darf_pago', 'custo_bonificacao')),
    period TEXT NOT NULL DEFAULT '',
    grupo TEXT NOT NULL DEFAULT '' CHECK (grupo IN ('', 'comum', 'day_trade', 'fii')),
    account_name TEXT NOT NULL DEFAULT '',
    ref_id INTEGER NOT NULL DEFAULT 0,
    amount_cents INTEGER NOT NULL,
    paid_on TEXT,
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (member_id, kind, period, grupo, account_name, ref_id)
);

-- Perfil fiscal do titular no ano-calendário.
CREATE TABLE IF NOT EXISTS ir_perfil (
    member_id INTEGER NOT NULL REFERENCES household_member(id),
    year INTEGER NOT NULL,
    contribui_previdencia_oficial INTEGER,  -- INSS, regime próprio ou aposentado (condição do PGBL); NULL: pelas fontes
    note TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id, year)
);

-- Fontes de renda: salário (CLT), pró-labore (PJ) ou outro rendimento tributável (aluguel, autônomo).
CREATE TABLE IF NOT EXISTS ir_fonte (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    year INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('clt', 'pro_labore', 'outro')),
    payer TEXT NOT NULL,
    payer_doc TEXT,
    gross_monthly_cents INTEGER NOT NULL CHECK (gross_monthly_cents >= 0),
    first_month INTEGER NOT NULL DEFAULT 1 CHECK (first_month BETWEEN 1 AND 12),
    last_month INTEGER NOT NULL DEFAULT 12 CHECK (last_month BETWEEN 1 AND 12),
    thirteenth INTEGER NOT NULL DEFAULT 1,
    vacation_month INTEGER CHECK (vacation_month IS NULL OR vacation_month BETWEEN 1 AND 12),
    inss_monthly_cents INTEGER,          -- NULL: calcula pela tabela
    irrf_year_cents INTEGER,             -- NULL: calcula mês a mês
    payroll_deductions_monthly_cents INTEGER NOT NULL DEFAULT 0,  -- pensão judicial descontada em folha
    pj_revenue_monthly_cents INTEGER,    -- PJ: faturamento médio do mês
    pj_regime TEXT CHECK (pj_regime IS NULL OR pj_regime IN ('simples_fator_r', 'simples_iii', 'simples_v', 'outro')),
    pj_profit_monthly_cents INTEGER,     -- PJ: lucro distribuído por mês
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ir_dependente (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    year INTEGER NOT NULL,
    name TEXT NOT NULL,
    kinship TEXT NOT NULL DEFAULT 'filho',
    birth_year INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tipo de dedução de uma categoria: os lançamentos dela contam, salvo marcação no lançamento.
CREATE TABLE IF NOT EXISTS ir_categoria_deducao (
    category TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('saude', 'educacao', 'pensao', 'doacao')),
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Marcação de um lançamento: manda na categoria. kind 'nenhuma' tira o lançamento das deduções.
CREATE TABLE IF NOT EXISTS ir_lancamento_deducao (
    transaction_id INTEGER PRIMARY KEY REFERENCES cash_transaction(id),
    kind TEXT NOT NULL CHECK (kind IN ('saude', 'educacao', 'pensao', 'doacao', 'nenhuma')),
    beneficiary TEXT NOT NULL DEFAULT 'titular',   -- 'titular' ou 'dep:<id de ir_dependente>'
    provider_name TEXT,
    provider_doc TEXT,                             -- CPF ou CNPJ do prestador (pedido na ficha Pagamentos Efetuados)
    subkind TEXT,
    reimbursed_cents INTEGER NOT NULL DEFAULT 0,
    author TEXT NOT NULL DEFAULT 'usuario',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Despesa dedutível que não passou pelo extrato (dinheiro, outra conta). Excluir marca deleted_at.
CREATE TABLE IF NOT EXISTS ir_deducao_manual (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL DEFAULT 1 REFERENCES household_member(id),
    paid_on TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('saude', 'educacao', 'pensao', 'doacao')),
    beneficiary TEXT NOT NULL DEFAULT 'titular',
    provider_name TEXT NOT NULL,
    provider_doc TEXT,
    subkind TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reimbursed_cents INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

-- Aportes de previdência, com quem pagou: só o do participante deduz (até 12%); o da empresa não.
CREATE TABLE IF NOT EXISTS previdencia_aporte (
    id INTEGER PRIMARY KEY,
    product_key TEXT NOT NULL,
    paid_on TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    payer TEXT NOT NULL CHECK (payer IN ('participante', 'empresa')),
    payroll INTEGER NOT NULL DEFAULT 0,       -- descontado em folha (já reduz o IRRF do mês)
    transaction_id INTEGER REFERENCES cash_transaction(id),
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_previdencia_aporte_plano ON previdencia_aporte(product_key, paid_on);
