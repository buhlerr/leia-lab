-- Foundation schema (prototype F, bead leia-lab-1g1.9). Idempotent: safe to re-run.
-- Layers: domain tables -> append-only history (trigger) -> analyses + trail (+ snapshot).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'leia_app') THEN
        CREATE ROLE leia_app NOLOGIN;  -- the role the application/management tools should use
    END IF;
END $$;

-- ---------------------------------------------------------------- domain tables
CREATE TABLE IF NOT EXISTS minuta_types (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    classifier_description TEXT NOT NULL,  -- criterion text the classifier sees for this type
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS themes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    minuta_type_id BIGINT NOT NULL REFERENCES minuta_types(id),
    slug TEXT NOT NULL,
    description TEXT,
    norm_ids TEXT[] NOT NULL DEFAULT '{}',  -- DEFAULT_TEMA_MAP: norm ids always fetched for the theme
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
    -- [{"id": ..., "citacao": ..., ...}]; "citacao" is mandatory (see leia-lab-vz3 handling in seed.py).
    norms JSONB NOT NULL DEFAULT '[]'::jsonb,
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
    model TEXT,                   -- NULL = the configured default chat model
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (minuta_type_id, kind, position)
);

-- ---------------------------------------------------------------- append-only history
CREATE TABLE IF NOT EXISTS domain_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    row_id BIGINT NOT NULL,
    op TEXT NOT NULL CHECK (op IN ('INSERT', 'UPDATE', 'DELETE')),
    old_row JSONB,
    new_row JSONB,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    db_user TEXT NOT NULL DEFAULT session_user
);
CREATE INDEX IF NOT EXISTS idx_domain_history_row ON domain_history (table_name, row_id, id);

-- SECURITY DEFINER: the log is written even when the writer has no rights on the history table.
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

CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed (append-only / audited table)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['minuta_types', 'themes', 'risk_matrix', 'prompts'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I
                        FOR EACH ROW EXECUTE FUNCTION domain_history_log()', t || '_history', t);
        -- TRUNCATE would skip the row triggers (and so the history): forbid it.
        EXECUTE format('CREATE OR REPLACE TRIGGER %I BEFORE TRUNCATE ON %I
                        FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()', t || '_no_truncate', t);
    END LOOP;
END $$;

CREATE OR REPLACE TRIGGER domain_history_append_only
    BEFORE UPDATE OR DELETE ON domain_history FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE OR REPLACE TRIGGER domain_history_no_truncate
    BEFORE TRUNCATE ON domain_history FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------- analyses + trail + snapshot
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'running',
    filename_alias TEXT NOT NULL,          -- documento-<sha8>.<ext>, never the real file name
    text_sha256 TEXT NOT NULL,             -- hash of the MASKED text
    params JSONB NOT NULL DEFAULT '{}'::jsonb,  -- cutoffs etc.
    -- Exact rules used, read atomically when the analysis started (JSON + hash).
    rules_snapshot JSONB NOT NULL,
    rules_hash TEXT NOT NULL,
    matrix_version TEXT NOT NULL,          -- content hash of themes + risks
    prompt_version TEXT NOT NULL,          -- content hash of prompts + classifier descriptions
    domain_history_id BIGINT NOT NULL,     -- domain_history watermark at read time
    minuta_type TEXT,
    report JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- Only status/minuta_type/report/finished_at may change; the snapshot is frozen.
CREATE OR REPLACE FUNCTION analyses_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE on analyses is not allowed' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (OLD.id, OLD.filename_alias, OLD.text_sha256, OLD.params, OLD.rules_snapshot, OLD.rules_hash,
        OLD.matrix_version, OLD.prompt_version, OLD.domain_history_id, OLD.started_at)
       IS DISTINCT FROM
       (NEW.id, NEW.filename_alias, NEW.text_sha256, NEW.params, NEW.rules_snapshot, NEW.rules_hash,
        NEW.matrix_version, NEW.prompt_version, NEW.domain_history_id, NEW.started_at) THEN
        RAISE EXCEPTION 'analyses snapshot columns are immutable' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER analyses_guard BEFORE UPDATE OR DELETE ON analyses
    FOR EACH ROW EXECUTE FUNCTION analyses_guard();

CREATE TABLE IF NOT EXISTS analysis_trail (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    seq INT NOT NULL,
    step TEXT NOT NULL,
    clause_n INT,
    input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,   -- MASKED summaries only
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

-- ---------------------------------------------------------------- grants for app roles
GRANT USAGE ON SCHEMA public TO leia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON minuta_types, themes, risk_matrix, prompts TO leia_app;
GRANT SELECT ON domain_history TO leia_app;                 -- no INSERT/UPDATE/DELETE on history
GRANT SELECT, INSERT, UPDATE ON analyses TO leia_app;       -- no DELETE; snapshot columns frozen by trigger
GRANT SELECT, INSERT ON analysis_trail TO leia_app;         -- no UPDATE/DELETE
GRANT SELECT, INSERT, UPDATE, DELETE ON kb_docs, kb_chunks TO leia_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO leia_app;
