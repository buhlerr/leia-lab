"""Nothing raw may sit in graph state / checkpoints / trail / snapshot (research finding, 9.7 item 5)."""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.foundation.seed import seed_defaults
from src.graphs.analyze_minuta_graph import AnalyzeMinutaState, analyze, analyze_stream, build_analyze_minuta_graph

NAME = "Carlos Eduardo Mendes"
CPF = "999.888.777-66"
CPF_DIGITS = "99988877766"
FILE_NAME = "minuta_Carlos_Eduardo_Mendes.txt"

RAW = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    f"LOCADOR: {NAME}, brasileiro, casado, CPF {CPF}, e-mail carlos.mendes@exemplo.com.br.\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M, "
    "conforme ajustado entre as partes neste instrumento contratual de locação."
)
SECRETS = [NAME, CPF, CPF_DIGITS, "Mendes", "carlos.mendes@exemplo.com.br", FILE_NAME, "Carlos_Eduardo"]


def _assert_clean(blob: str, where: str) -> None:
    low = blob.lower()
    for s in SECRETS:
        assert s.lower() not in low, f"{s!r} leaked into {where}"


def test_graph_state_schema_has_no_raw_text_or_path_field():
    assert not {"raw_text", "file_path"} & set(AnalyzeMinutaState.__annotations__)


async def test_no_raw_text_reaches_state_checkpoints_trail_or_snapshot(fpool, settings):
    await seed_defaults(fpool)
    saver = InMemorySaver()
    graph = build_analyze_minuta_graph(fpool, settings, checkpointer=saver)
    cfg = {"configurable": {"thread_id": "t1"}}

    out = await analyze(graph, raw_text=RAW, filename=FILE_NAME, config=cfg)
    assert out["suportado"] is True  # the run actually went through every step
    assert "[CPF]" in out["text"] and "[NOME]" in out["text"]

    _assert_clean(json.dumps(out, ensure_ascii=False, default=str), "final state")
    history = [s async for s in graph.aget_state_history(cfg)]
    assert len(history) > 3
    for snap in history:  # what a checkpointer (or a tracer) would persist/export at every super-step
        _assert_clean(json.dumps(snap.values, ensure_ascii=False, default=str), "checkpoint values")
        _assert_clean(repr(snap.metadata), "checkpoint metadata")
    _assert_clean(repr(saver.storage), "checkpointer storage")

    rows = await fpool.fetch("SELECT to_jsonb(t)::text AS j FROM analysis_trail t")
    assert rows
    for r in rows:
        _assert_clean(r["j"], "analysis_trail")
    for r in await fpool.fetch("SELECT to_jsonb(a)::text AS j FROM analyses a"):
        _assert_clean(r["j"], "analyses (snapshot/report)")


async def test_streamed_updates_never_carry_raw_text(fpool, settings):
    """Every per-node update (what a streaming tracer receives) is clean as well."""
    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    seen = []
    async for chunk in analyze_stream(graph, raw_text=RAW, filename=FILE_NAME, stream_mode="updates"):
        seen.append(chunk)
    assert len(seen) >= 6
    _assert_clean(json.dumps(seen, ensure_ascii=False, default=str), "streamed updates")


async def test_graph_refuses_unmasked_input_passed_directly(fpool, settings):
    """Bypassing analyze() with a raw_text key must not smuggle text in: the graph needs masked text."""
    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    with pytest.raises(Exception) as exc:  # noqa: PT011 - any failure is acceptable, a silent run is not
        await graph.ainvoke({"raw_text": RAW, "filename": FILE_NAME})
    assert NAME not in str(exc.value) and CPF not in str(exc.value)
