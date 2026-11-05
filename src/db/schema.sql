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
