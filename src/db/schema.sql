CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_docs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'kb',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID REFERENCES kb_docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    sequence_order INT NOT NULL,
    tsv_content TSVECTOR GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED,
    embedding VECTOR(1536),
    -- Procedencia do vetor: sem isso, trocar de modelo de embedding mistura
    -- vetores incomparaveis no mesmo indice, em silencio.
    embedding_model TEXT,
    indexed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Idempotencia para bancos criados antes destas colunas existirem.
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- High Performance Indexes
CREATE INDEX IF NOT EXISTS idx_kb_chunks_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv ON kb_chunks USING gin (tsv_content);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id ON kb_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_model ON kb_chunks(embedding_model);

-- =====================================================================
-- Esquema de dominio (M1, leia-lab-8tr.1). Reescrito de prototype/foundation.
-- Idempotente: roda em banco vazio e em banco que ja tem kb_docs/kb_chunks
-- (ou tabelas de terceiros, como as directus_*, que nao sao tocadas).
-- Camadas: tabelas de dominio -> historico append-only (gatilho)
--          -> analyses + analysis_trail (snapshot congelado).
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'leia_app') THEN
        CREATE ROLE leia_app NOLOGIN;  -- papel do motor e do admin; logins pessoais recebem este papel
    END IF;
END $$;

-- ---------------------------------------------------------------- tabelas de dominio
CREATE TABLE IF NOT EXISTS minuta_types (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    classifier_description TEXT NOT NULL,  -- criterio que o classificador ve para este tipo
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS themes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    minuta_type_id BIGINT NOT NULL REFERENCES minuta_types(id),
    slug TEXT NOT NULL,
    description TEXT,
    norm_ids TEXT[] NOT NULL DEFAULT '{}',  -- normas sempre buscadas para o tema (DEFAULT_TEMA_MAP)
    position INT NOT NULL DEFAULT 0,
    UNIQUE (minuta_type_id, slug)
);

CREATE TABLE IF NOT EXISTS risk_matrix (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    theme_id BIGINT NOT NULL REFERENCES themes(id),
    risk_id TEXT NOT NULL,
    description TEXT NOT NULL,
    criticality TEXT NOT NULL CHECK (criticality IN ('vermelho', 'amarelo', 'verde')),
    party TEXT NOT NULL DEFAULT 'locatario',
    norms JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{"id": ..., "citacao": ...}]
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (theme_id, risk_id),
    CHECK (jsonb_typeof(norms) = 'array')
);

CREATE TABLE IF NOT EXISTS prompts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    minuta_type_id BIGINT NOT NULL REFERENCES minuta_types(id),
    kind TEXT NOT NULL,           -- redigir_system | triagem_risco | confirmar_risco | regula_norma
    position INT NOT NULL DEFAULT 0,
    prompt_text TEXT NOT NULL,
    model TEXT,                   -- NULL = modelo de chat configurado por padrao
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (minuta_type_id, kind, position)
);

-- ---------------------------------------------------------------- historico append-only
CREATE TABLE IF NOT EXISTS domain_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    row_id BIGINT NOT NULL,
    op TEXT NOT NULL CHECK (op IN ('INSERT', 'UPDATE', 'DELETE')),
    old_row JSONB,
    new_row JSONB,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    -- session_user (e nao current_user): com SET ROLE leia_app continua sendo o login de quem escreveu.
    db_user TEXT NOT NULL DEFAULT session_user
);
CREATE INDEX IF NOT EXISTS idx_domain_history_row ON domain_history (table_name, row_id, id);

-- SECURITY DEFINER: o log e gravado mesmo quando quem escreve nao tem direito sobre o historico.
CREATE OR REPLACE FUNCTION domain_history_log() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO domain_history (table_name, row_id, op, new_row)
        VALUES (TG_TABLE_NAME, NEW.id, 'INSERT', to_jsonb(NEW));
    ELSIF TG_OP = 'UPDATE' THEN
        IF to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN
            INSERT INTO domain_history (table_name, row_id, op, old_row, new_row)
            VALUES (TG_TABLE_NAME, NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW));
        END IF;
    ELSE
        INSERT INTO domain_history (table_name, row_id, op, old_row)
        VALUES (TG_TABLE_NAME, OLD.id, 'DELETE', to_jsonb(OLD));
    END IF;
    RETURN NULL;
END $$;
-- Sem EXECUTE para PUBLIC (herdado por leia_api/leia_readonly): qualquer papel com TEMP no
-- banco forjaria entradas indeletaveis no historico via tabela temporaria + gatilho proprio.
REVOKE ALL ON FUNCTION domain_history_log() FROM PUBLIC;

CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed (append-only / audited table)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;
REVOKE ALL ON FUNCTION forbid_change() FROM PUBLIC;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['minuta_types', 'themes', 'risk_matrix', 'prompts'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I
                        FOR EACH ROW EXECUTE FUNCTION domain_history_log()', t || '_history', t);
        -- TRUNCATE pula os gatilhos de linha (e portanto o historico): proibido.
        EXECUTE format('CREATE OR REPLACE TRIGGER %I BEFORE TRUNCATE ON %I
                        FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()', t || '_no_truncate', t);
    END LOOP;
END $$;

CREATE OR REPLACE TRIGGER domain_history_append_only
    BEFORE UPDATE OR DELETE ON domain_history FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE OR REPLACE TRIGGER domain_history_no_truncate
    BEFORE TRUNCATE ON domain_history FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------- versoes de dados aplicadas
-- Ledger append-only: cada versao de dado do repo (data/matriz/v1, data/base-normativa/v1...)
-- entra no banco uma vez so, com o sha256 conferido. Depois disso o banco e a fonte da verdade.
CREATE TABLE IF NOT EXISTS data_versions (
    name TEXT PRIMARY KEY,           -- ex.: matriz/v1
    sha256 TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    db_user TEXT NOT NULL DEFAULT session_user
);
CREATE OR REPLACE TRIGGER data_versions_append_only
    BEFORE UPDATE OR DELETE ON data_versions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE OR REPLACE TRIGGER data_versions_no_truncate
    BEFORE TRUNCATE ON data_versions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------- analyses + trilha + snapshot
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'running',
    filename_alias TEXT NOT NULL,               -- documento-<sha8>.<ext>, nunca o nome real
    text_sha256 TEXT NOT NULL,                  -- hash do texto MASCARADO
    params JSONB NOT NULL DEFAULT '{}'::jsonb,  -- cutoffs etc.
    rules_snapshot JSONB NOT NULL,              -- regras exatas lidas no inicio da analise
    rules_hash TEXT NOT NULL,
    matrix_version TEXT NOT NULL,               -- hash de conteudo de temas + riscos
    prompt_version TEXT NOT NULL,               -- hash de conteudo de prompts + descricoes do classificador
    domain_history_id BIGINT NOT NULL,          -- marca de leitura do domain_history
    minuta_type TEXT,
    report JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    idempotency_key TEXT                        -- header Idempotency-Key do POST da API; NULL na CLI
);
-- Uma analise por chave: o INSERT do retry vira ON CONFLICT DO NOTHING. Banco anterior a coluna a
-- ganha vazia (linhas antigas sem chave). O ALTER so roda se faltar: ADD COLUMN IF NOT EXISTS pediria
-- ACCESS EXCLUSIVE em analyses a cada init, mesmo sem nada a fazer.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'analyses'::regclass AND attname = 'idempotency_key' AND NOT attisdropped
    ) THEN
        ALTER TABLE analyses ADD COLUMN idempotency_key TEXT;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS analyses_idempotency_key ON analyses (idempotency_key);
-- Ciclo de vida: running -> done | unsupported | failed. Status fora do ciclo em banco legado e
-- normalizado para 'failed' (valor original no report) ANTES do CHECK; o CHECK em si so e criado
-- se ainda nao existe -- sem o DROP+ADD de antes, que revalidava e trancava a tabela a cada init.
UPDATE analyses SET status = 'failed',
                    report = jsonb_build_object('error', 'StatusForaDoCiclo', 'status_original', status),
                    finished_at = now()
WHERE status NOT IN ('running', 'done', 'unsupported', 'failed');
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'analyses_status_check' AND conrelid = 'analyses'::regclass
    ) THEN
        ALTER TABLE analyses ADD CONSTRAINT analyses_status_check
            CHECK (status IN ('running', 'done', 'unsupported', 'failed'));
    END IF;
END $$;

-- So status/minuta_type/report/finished_at mudam, e so enquanto 'running'; o snapshot e congelado.
CREATE OR REPLACE FUNCTION analyses_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE on analyses is not allowed' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status NOT IN ('running', 'done', 'unsupported', 'failed') AND NEW.status = 'failed' THEN
        RETURN NEW;  -- linha anterior ao CHECK: so a normalizacao para 'failed' passa
    END IF;
    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'analysis % is finished (%): its row is immutable', OLD.id, OLD.status
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (OLD.id, OLD.filename_alias, OLD.text_sha256, OLD.params, OLD.rules_snapshot, OLD.rules_hash,
        OLD.matrix_version, OLD.prompt_version, OLD.domain_history_id, OLD.started_at, OLD.idempotency_key)
       IS DISTINCT FROM
       (NEW.id, NEW.filename_alias, NEW.text_sha256, NEW.params, NEW.rules_snapshot, NEW.rules_hash,
        NEW.matrix_version, NEW.prompt_version, NEW.domain_history_id, NEW.started_at, NEW.idempotency_key) THEN
        RAISE EXCEPTION 'analyses snapshot columns are immutable' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER analyses_guard BEFORE UPDATE OR DELETE ON analyses
    FOR EACH ROW EXECUTE FUNCTION analyses_guard();
REVOKE ALL ON FUNCTION analyses_guard() FROM PUBLIC;
CREATE OR REPLACE TRIGGER analyses_no_truncate
    BEFORE TRUNCATE ON analyses FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

CREATE TABLE IF NOT EXISTS analysis_trail (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    seq INT NOT NULL,
    step TEXT NOT NULL,
    clause_n INT,
    input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,  -- so resumos MASCARADOS
    decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    score DOUBLE PRECISION,
    cutoff DOUBLE PRECISION,
    matrix_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    cited_norms TEXT[] NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (analysis_id, seq)
);
CREATE OR REPLACE TRIGGER analysis_trail_append_only
    BEFORE UPDATE OR DELETE ON analysis_trail FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE OR REPLACE TRIGGER analysis_trail_no_truncate
    BEFORE TRUNCATE ON analysis_trail FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------- grants do papel da aplicacao
GRANT USAGE ON SCHEMA public TO leia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON minuta_types, themes, risk_matrix, prompts TO leia_app;
GRANT SELECT ON domain_history TO leia_app;                 -- sem escrita no historico
GRANT SELECT ON data_versions TO leia_app;                  -- aplicar versao de dado e tarefa de operacao (dono do schema)
GRANT SELECT, INSERT, UPDATE ON analyses TO leia_app;       -- sem DELETE; snapshot congelado por gatilho
GRANT SELECT, INSERT ON analysis_trail TO leia_app;         -- sem UPDATE/DELETE
GRANT SELECT, INSERT, UPDATE, DELETE ON kb_docs, kb_chunks TO leia_app;
-- So as sequencias da Leia, nunca ALL SEQUENCES: o banco do homelab e compartilhado com o Directus.
GRANT USAGE ON SEQUENCE minuta_types_id_seq, themes_id_seq, risk_matrix_id_seq, prompts_id_seq,
    analysis_trail_id_seq TO leia_app;

-- ---------------------------------------------------------------- papeis minimos (VIT-22)
-- leia_api: o que a API grava e le. A matriz e so leitura (quem edita e o admin, com leia_app);
-- a analise e o unico caminho de escrita: INSERT da linha, UPDATE do termino (grants por coluna
-- + gatilho analyses_guard congelam o resto) e INSERT da trilha, que e append-only por gatilho.
-- leia_readonly: leitura do dominio inteiro, sem nenhuma escrita. Logins pessoais recebem
-- um destes papeis (GRANT leia_api TO api_login); sao NOLOGIN de proposito.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'leia_api') THEN
        CREATE ROLE leia_api NOLOGIN;   -- papel da API (api_login na producao)
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'leia_readonly') THEN
        CREATE ROLE leia_readonly NOLOGIN;  -- papel de consulta, sem escrita
    END IF;
END $$;
-- Convergencia, nao acumulacao: revoga antes de conceder, para um init em banco existente
-- remover grant excedente de versao anterior. So as tabelas e sequencias da Leia; o banco do
-- homelab e compartilhado com o Directus (directus_* intocadas).
REVOKE ALL ON TABLE minuta_types, themes, risk_matrix, prompts, domain_history, data_versions,
    analyses, analysis_trail, kb_docs, kb_chunks FROM leia_api, leia_readonly;
REVOKE ALL ON SEQUENCE minuta_types_id_seq, themes_id_seq, risk_matrix_id_seq, prompts_id_seq,
    analysis_trail_id_seq FROM leia_api, leia_readonly;
GRANT USAGE ON SCHEMA public TO leia_api, leia_readonly;
GRANT SELECT ON minuta_types, themes, risk_matrix, prompts, domain_history,
    kb_docs, kb_chunks TO leia_api;
GRANT SELECT, INSERT ON analyses TO leia_api;
-- UPDATE so das colunas que o termino toca (finish/fail em src/db/analyses.py): coluna nova
-- nasce bloqueada para a API, alem do gatilho analyses_guard.
GRANT UPDATE (status, minuta_type, report, finished_at) ON analyses TO leia_api;
GRANT SELECT, INSERT ON analysis_trail TO leia_api;          -- sem UPDATE/DELETE: trilha append-only
GRANT USAGE ON SEQUENCE analysis_trail_id_seq TO leia_api;
GRANT SELECT ON minuta_types, themes, risk_matrix, prompts, domain_history, data_versions,
    analyses, analysis_trail, kb_docs, kb_chunks TO leia_readonly;
