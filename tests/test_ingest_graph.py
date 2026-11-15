import pytest

from src.db.connection import init_db
from src.graphs.ingest_graph import build_ingest_graph


async def test_ingest_graph_masks_splits_and_indexes_into_pgvector(pool, settings):
    await init_db(pool)
    graph = build_ingest_graph(pool, settings)

    raw_contract = (
        "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
        "LOCADOR: Maria Oliveira Santos, brasileira, solteira, CPF 111.222.333-44.\n"
        "Cláusula 1ª - O prazo da locação é de 30 meses a partir de 01/02/2026.\n"
        "Cláusula 2ª - O aluguel mensal é de R$ 2.500,00 reajustado pelo IPCA."
    )
    result = await graph.ainvoke(
        {
            "raw_text": raw_contract,
            "filename": "contrato_original.txt",
            "chunk_size": 120,
            "chunk_overlap": 20,
        }
    )

    assert "Maria Oliveira Santos" not in result["masked_text"]
    assert "111.222.333-44" not in result["masked_text"]
    assert "[NOME]" in result["masked_text"]
    assert "[CPF]" in result["masked_text"]
    assert result["resolved_filename"].startswith("documento-")
    assert result["chunks_indexed"] == len(result["chunks"])
    assert result["chunks_indexed"] >= 2

    doc_row = await pool.fetchrow("SELECT title, source FROM kb_docs WHERE id = $1::uuid", result["doc_id"])
    assert doc_row["title"] == result["resolved_filename"]
    chunk_rows = await pool.fetch(
        "SELECT content, embedding_model FROM kb_chunks WHERE doc_id = $1::uuid ORDER BY sequence_order",
        result["doc_id"],
    )
    assert len(chunk_rows) == result["chunks_indexed"]
    assert all("111.222.333-44" not in r["content"] for r in chunk_rows)
    assert all(r["embedding_model"] == settings.EMBEDDING_MODEL for r in chunk_rows)


async def test_ingest_graph_rejects_empty_text(pool, settings):
    await init_db(pool)
    graph = build_ingest_graph(pool, settings)
    with pytest.raises(ValueError, match="non-empty"):
        await graph.ainvoke({"raw_text": "   \n  ", "filename": "vazio.txt"})
    assert await pool.fetchval("SELECT count(*) FROM kb_docs") == 0
