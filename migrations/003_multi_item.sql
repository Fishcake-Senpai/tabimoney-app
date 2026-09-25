-- Vários itens do Meu Pluggy (ex.: Nubank e Itaú): a lista substitui o Item ID único.
INSERT OR IGNORE INTO app_setting(key, value)
SELECT 'pluggy_item_ids', value FROM app_setting WHERE key = 'pluggy_item_id' AND TRIM(value) <> '';

-- Data de aplicação da renda fixa: reconstrói o histórico antes da primeira fotografia.
ALTER TABLE fixed_income_snapshot ADD COLUMN purchase_date TEXT;
