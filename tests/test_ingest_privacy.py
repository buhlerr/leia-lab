"""M6 (leia-lab-8wy): a ingestao tambem nunca guarda texto cru no estado do grafo."""

from __future__ import annotations

import json
import typing

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import src.graphs.ingest_graph as ing
from src.db.connection import init_db
from src.graphs.analyze_minuta_graph import AnalyzeMinutaState
from src.graphs.ingest_graph import IngestState, build_ingest_graph, ingest, prepare_ingest_input

NAME = "Maria Oliveira Santos"
CPF = "111.222.333-44"
FILE_NAME = "parecer_Maria_Oliveira.txt"
RAW = (
    "LEI DE TESTE, art. 1. O locador nao pode exigir mais de uma garantia.\n"
    f"Comentario de {NAME}, CPF {CPF}, e-mail maria.santos@exemplo.com.br, sobre o artigo.\n"
    "Art. 2. A multa rescisoria e proporcional ao prazo cumprido."
)
SECRETS = [NAME, "Oliveira Santos", CPF, "11122233344", "maria.santos@exemplo.com.br", FILE_NAME, "Maria_Oliveira"]
RAW_FIELDS = {"raw_text", "file_path", "doc_name"}  # "filename" no grafo de analise e o apelido publico


def _found(blob: str) -> list[str]:
    low = blob.lower()
    return [s for s in SECRETS if s.lower() in low]


async def _leaks(pool, settings) -> dict[str, list[str]]:
    await init_db(pool)
    saver = InMemorySaver()
    graph = build_ingest_graph(pool, settings, checkpointer=saver)
    cfg = {"configurable": {"thread_id": "ing-1"}}
    inp = await prepare_ingest_input(raw_text=RAW, filename=FILE_NAME, chunk_size=80, chunk_overlap=10)
    updates = [c async for c in graph.astream(inp, cfg, stream_mode="updates")]
    final = (await graph.aget_state(cfg)).values
    checkpoints = [s async for s in graph.aget_state_history(cfg)]
    assert final.get("chunks_indexed", 0) >= 2 and len(checkpoints) > 2
    rows = await pool.fetch("SELECT d.title, d.metadata::text AS m, c.content FROM kb_docs d JOIN kb_chunks c ON c.doc_id = d.id")
    places = {
        "estado": json.dumps(final, ensure_ascii=False, default=str),
        "checkpoint": json.dumps([c.values for c in checkpoints], ensure_ascii=False, default=str) + repr(saver.storage),
        "updates por no": json.dumps(updates, ensure_ascii=False, default=str),
        "banco": json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str),
    }
    return {k: _found(v) for k, v in places.items()}


@pytest.mark.parametrize("state", [IngestState, AnalyzeMinutaState])
def test_no_graph_in_the_repo_has_raw_text_in_its_state(state):
    assert not RAW_FIELDS & set(typing.get_type_hints(state))


async def test_ingest_keeps_no_personal_data_in_state_checkpoint_updates_or_db(pool, settings):
    assert await _leaks(pool, settings) == {"estado": [], "checkpoint": [], "updates por no": [], "banco": []}


async def test_the_ingest_scan_catches_the_leak_when_masking_is_off(pool, settings, monkeypatch):
    monkeypatch.setattr(ing, "mask_personal_data", lambda text: text)
    monkeypatch.setattr(ing, "resolve_doc_alias", lambda filename, doc_name="": filename)
    leaks = await _leaks(pool, settings)
    for place, found in leaks.items():
        assert NAME in found and CPF in found, place


@pytest.mark.parametrize(
    "bad", [{"raw_text": RAW, "filename": "x.txt"}, {"masked_text": RAW, "resolved_filename": "documento-x.txt"}]
)
async def test_ingest_graph_refuses_input_that_did_not_go_through_ingest(pool, settings, bad):
    await init_db(pool)
    with pytest.raises(ValueError, match="ingest") as exc:
        await build_ingest_graph(pool, settings).ainvoke(bad)
    assert not _found(str(exc.value))
    assert await pool.fetchval("SELECT count(*) FROM kb_docs") == 0


async def test_prepare_refuses_unknown_fields():
    with pytest.raises(TypeError, match="raw"):
        await prepare_ingest_input(raw_text="x", raw="y")


async def test_ingest_helper_still_returns_the_masked_result(pool, settings):
    await init_db(pool)
    out = await ingest(build_ingest_graph(pool, settings), raw_text=RAW, filename=FILE_NAME, doc_name="Lei de teste, art. 1")
    assert "[CPF]" in out["masked_text"] and out["resolved_filename"] == "Lei de teste, art. 1"
