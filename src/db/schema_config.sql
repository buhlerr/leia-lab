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
-- Os nomes acima sao fixos. TUDO MAIS e sua decisao.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- TODO(human): escreva aqui o CREATE TABLE das duas tabelas.
