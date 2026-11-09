"""Fictitious demo data: a minuta type, its reports and a small knowledge base.

Everything here is invented. The seed is idempotent: running it twice leaves the
same rows in place, and prompts already edited with an ``UPDATE`` are never
overwritten.
"""

from __future__ import annotations

import asyncio

import asyncpg

from src.config import Settings
from src.db.connection import init_db
from src.rag.embeddings import get_embedding
from src.rag.hybrid_search import _to_pgvector_literal

DEMO_TYPE_NAME = "Prestacao de Servicos (demo)"
DEMO_SOURCE = "demo"
# Sem chave de API o vetor e simulado; registrar o modelo real seria falsear a procedencia.
OFFLINE_EMBEDDING_LABEL = "offline-deterministic"

DEMO_REPORTS = [
    {
        "name": "Resumo do objeto",
        "kind": "parecer",
        "execution_order": 1,
        "prompt": (
            "Resuma o objeto do contrato apresentado em no maximo cinco linhas. "
            "Descreva o que esta sendo contratado, por quem e para qual finalidade, "
            "sem reproduzir clausulas inteiras."
        ),
    },
    {
        "name": "Clausulas essenciais",
        "kind": "checklist",
        "execution_order": 2,
        "prompt": (
            "Verifique a minuta quanto a objeto, prazo, valor, rescisao e foro. "
            "Para cada item, informe o status 'presente', 'ausente' ou 'divergente' "
            "e transcreva a evidencia encontrada. Consulte a base de conhecimento "
            "com a ferramenta search_kb antes de concluir."
        ),
    },
    {
        "name": "Parecer de riscos",
        "kind": "parecer",
        "execution_order": 3,
        "prompt": (
            "Liste os riscos para a contratante, considerando obrigacoes assumidas, "
            "prazos, valores e penalidades. Cite os trechos encontrados na base de "
            "conhecimento usando a ferramenta search_kb e explique o impacto de cada risco."
        ),
    },
]

DEMO_DOCS = [
    {
        "title": "Rescisao contratual: boas praticas",
        "content": (
            "Boa pratica ficticia: o contrato deve prever a rescisao sem justa causa "
            "com aviso previo proporcional, a rescisao por descumprimento com prazo de "
            "cura e a forma de calculo dos valores devidos pelos servicos ja executados. "
            "Sem clausula de rescisao, a parte que quiser encerrar o contrato fica "
            "dependente de negociacao caso a caso."
        ),
    },
    {
        "title": "Reajuste de precos: boas praticas",
        "content": (
            "Boa pratica ficticia: o reajuste anual deve indicar o indice de precos "
            "aplicavel, a periodicidade minima de doze meses e a data-base do contrato. "
            "Tambem e recomendavel prever o que acontece se o indice for extinto, "
            "elegendo um substituto oficial. Reajuste sem indice definido costuma gerar "
            "divergencia entre as partes."
        ),
    },
    {
        "title": "Foro de eleicao: boas praticas",
        "content": (
            "Boa pratica ficticia: a clausula de foro deve eleger a comarca onde as "
            "partes efetivamente negociam, evitando foros distantes que dificultem a "
            "defesa. A ausencia de clausula de foro nao impede o contrato, mas deixa a "
            "competencia para as regras gerais de processo, o que pode surpreender as partes."
        ),
    },
    {
        "title": "Multa contratual: boas praticas",
        "content": (
            "Boa pratica ficticia: a multa contratual deve ter base de calculo clara, "
            "limite proporcional ao valor do contrato e indicacao do que a caracteriza. "
            "Multas muito altas podem ser reduzidas pelo juizo, enquanto multas sem "
            "hipotese definida raramente sao aplicaveis. E recomendavel distinguir multa "
            "moratoria de multa compensatoria."
        ),
    },
]


def _embedding_label(settings: Settings) -> str:
    """Name the vector's real origin: offline vectors are not the configured model."""
    return settings.EMBEDDING_MODEL if settings.OPENROUTER_API_KEY else OFFLINE_EMBEDDING_LABEL


async def _docs_to_embed(pool: asyncpg.Pool, label: str) -> list[dict[str, str]]:
    """Return the demo documents that are missing or were embedded by another origin."""
    rows = await pool.fetch(
        """
        SELECT d.title
        FROM kb_docs d
        JOIN kb_chunks c ON c.doc_id = d.id
        WHERE d.source = $1 AND c.embedding_model = $2
        """,
        DEMO_SOURCE,
        label,
    )
    current = {row["title"] for row in rows}
    return [doc for doc in DEMO_DOCS if doc["title"] not in current]


async def _seed_type_and_reports(conn: asyncpg.Connection) -> None:
    """Insert the demo type and its reports without touching existing rows."""
    await conn.execute(
        "INSERT INTO minuta_types (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
        DEMO_TYPE_NAME,
    )
    type_id = await conn.fetchval(
        "SELECT id FROM minuta_types WHERE name = $1", DEMO_TYPE_NAME
    )

    for report in DEMO_REPORTS:
        await conn.execute(
            """
            INSERT INTO minuta_reports
                (minuta_type_id, name, kind, prompt, model, execution_order)
            VALUES ($1, $2, $3, $4, NULL, $5)
            ON CONFLICT (minuta_type_id, name) DO NOTHING
            """,
            type_id,
            report["name"],
            report["kind"],
            report["prompt"],
            report["execution_order"],
        )


async def _seed_docs(
    conn: asyncpg.Connection,
    docs: list[dict[str, str]],
    embeddings: dict[str, list[float]],
    settings: Settings,
) -> None:
    """Insert one chunk per missing demo document, tagged with the embedding model."""
    for doc in docs:
        doc_id = await conn.fetchval(
            "INSERT INTO kb_docs (title, source) VALUES ($1, $2) RETURNING id",
            doc["title"],
            DEMO_SOURCE,
        )
        await conn.execute(
            """
            INSERT INTO kb_chunks
                (doc_id, content, sequence_order, embedding, embedding_model)
            VALUES ($1, $2, 0, $3::text::vector, $4)
            """,
            doc_id,
            doc["content"],
            _to_pgvector_literal(embeddings[doc["title"]]),
            _embedding_label(settings),
        )


async def seed_demo(pool: asyncpg.Pool, settings: Settings) -> None:
    """Seed the demo type, reports and knowledge base in a single transaction."""
    docs = await _docs_to_embed(pool, _embedding_label(settings))
    # Embeddings primeiro: se o provedor falhar, nada do que existe e apagado.
    embeddings = {doc["title"]: await get_embedding(doc["content"], settings) for doc in docs}

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _seed_type_and_reports(conn)
            await conn.execute(
                "DELETE FROM kb_docs WHERE source = $1 AND title = ANY($2::text[])",
                DEMO_SOURCE,
                [doc["title"] for doc in docs],
            )
            await _seed_docs(conn, docs, embeddings, settings)


async def _seed_from_settings(settings: Settings) -> None:
    async with asyncpg.create_pool(dsn=settings.DATABASE_URL) as pool:
        await init_db(pool)
        await seed_demo(pool, settings)


def main() -> None:
    """Apply the schema and seed the demo data into ``DATABASE_URL``."""
    settings = Settings()
    asyncio.run(_seed_from_settings(settings))


if __name__ == "__main__":
    main()
