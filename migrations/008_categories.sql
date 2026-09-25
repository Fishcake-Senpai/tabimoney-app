-- Categorias criadas pelo usuário ou pelo agente. As categorias padrão (BASE_CATEGORIES) ficam no código.
-- name_key é o nome sem acento e sem caixa: 'Delivery' e 'delivery' são a mesma categoria.
-- Excluir não apaga a linha: marca deleted_at e guarda em undo o que foi movido, para poder restaurar.
CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    author TEXT NOT NULL DEFAULT 'usuario',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    moved_to TEXT,
    undo TEXT
);
