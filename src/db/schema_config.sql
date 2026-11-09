-- Configuracao da analise: tipos de minuta e seus relatorios.
--
-- Na LEIA original isso vive no SQL Server, em App.MinutaType e App.MinutaReport.
-- Aqui o objetivo e o mesmo: o prompt de cada relatorio e DADO, nao codigo. Mudar
-- um prompt deve ser um UPDATE, e a proxima execucao ja usa o texto novo.
--
-- Contrato que o resto do sistema espera (src/db/config_repo.py e os testes):
--   tabela minuta_types   -> id (UUID, PK), name (TEXT)
--   tabela minuta_reports -> id (UUID, PK), minuta_type_id (FK para minuta_types),
--                            name, kind, prompt, model, execution_order

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS minuta_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE CHECK (btrim(name) <> ''),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS minuta_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minuta_type_id UUID NOT NULL REFERENCES minuta_types(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    kind TEXT NOT NULL CHECK (kind IN ('parecer', 'checklist')),
    prompt TEXT NOT NULL CHECK (btrim(prompt) <> ''),
    -- NULL significa usar o CHAT_MODEL da aplicacao.
    model TEXT NULL CHECK (model IS NULL OR btrim(model) <> ''),
    execution_order INT NOT NULL CHECK (execution_order > 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Este indice tambem atende a consulta
    -- WHERE minuta_type_id = $1 ORDER BY execution_order.
    UNIQUE (minuta_type_id, execution_order),
    UNIQUE (minuta_type_id, name)
);
