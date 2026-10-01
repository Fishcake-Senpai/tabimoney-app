-- Ícone escolhido para uma categoria criada pelo usuário (nome de um ícone Lucide de app/static/icons.svg).
-- NULL: o app escolhe pelo nome (app/services/categories.py, category_icon).
ALTER TABLE category ADD COLUMN icon TEXT;
