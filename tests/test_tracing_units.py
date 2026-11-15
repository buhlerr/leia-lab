"""Conta as unidades de billing por análise a partir do payload OTLP real.

Unidade Langfuse = traço + observação + score. Este teste exporta uma análise
de verdade para um coletor local e conta os spans que o SDK produz (cada span
vira uma observação; a raiz vira o traço). Serve de orçamento verificável
contra o plano Hobby (50k unidades/mês).
"""

from __future__ import annotations

import gzip

from tests.test_foundation_privacy import FILE_NAME, RAW


def _plain(body: bytes) -> bytes:
    """Descomprime se o corpo vier em gzip (o exporter pode comprimir sem header)."""
    if body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body)
        except OSError:
            return body
    return body


def _count_spans(blob: bytes) -> int:
    """Conta spans no ExportTraceServiceRequest protobuf (repetição do campo 1)."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    request = ExportTraceServiceRequest()
    request.ParseFromString(_plain(blob))
    # proto novo: ResourceSpans.scope_spans[].spans (o alias antigo era instrumentation_library_spans)
    return sum(
        len(scope.spans) for rs in request.resource_spans for scope in rs.scope_spans
    )


async def test_unidades_por_analise_langfuse(fpool, settings, capture, monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{capture.port}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from src.tracing import force_flush, setup_tracing

    setup_tracing("langfuse")

    from src.foundation.seed import seed_defaults
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    await analyze(graph, raw_text=RAW, filename=FILE_NAME)
    force_flush()

    payloads = [b for b in capture.bodies if b]
    assert payloads, "nenhum payload OTLP exportado"
    spans = sum(_count_spans(b) for b in payloads)
    print(f"\nSPANS (observacoes) por analise sintetica (2 clausulas): {spans}")
    assert spans >= 5, f"esperado um punhado de spans por análise, veio {spans}"


async def test_unidades_no_gabarito_3_minutas(fpool, settings, capture, monkeypatch) -> None:
    """Número que importa para o orçamento: unidades do gabarito (3 minutas)."""
    from src.foundation import gold as G

    d = G.minutas_dir()
    problems = G.verify_gold(G.load_gold(), d)
    if problems:
        import pytest

        pytest.skip("minutas mascaradas ausentes: " + "; ".join(problems[:2]))

    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{capture.port}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from src.tracing import force_flush, setup_tracing

    setup_tracing("langfuse")

    from src.foundation.seed import seed_defaults
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    for name in G.load_gold()["minutas"]:
        await analyze(graph, file_path=d / name)
    force_flush()

    spans = sum(_count_spans(b) for b in capture.bodies if b)
    per_minuta = spans / 3
    print(f"\nGABARITO: {spans} observacoes / 3 minutas = {per_minuta:.1f} por analise")
    print(f"  + 3 tracos => ~{per_minuta + 1:.1f} unidades por analise")
    print(f"  orcamento Hobby 50k/mes => ~{int(50000 / (per_minuta + 1))} analises/mes")
    assert spans > 0
