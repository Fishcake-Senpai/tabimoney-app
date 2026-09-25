-- Compras em moeda estrangeira: amount_cents fica em reais (valor convertido pela Pluggy na data da compra);
-- aqui fica o valor original, só para exibição.
ALTER TABLE cash_transaction ADD COLUMN original_currency TEXT;
ALTER TABLE cash_transaction ADD COLUMN original_amount_cents INTEGER;
