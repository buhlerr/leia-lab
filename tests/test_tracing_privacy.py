"""Prova empírica (B3): nada de texto cru sai do processo para os colecionadores.

O fixture ``capture`` (tests/conftest.py) sobe um servidor HTTP local que
captura os payloads brutos (OTLP/protobuf do Langfuse/Phoenix; JSON do
LangSmith com cliente apontado para ele). PII conhecida da minuta sintética
NÃO pode aparecer; o conteúdo mascarado tem de aparecer (prova de que o trace
real foi capturado, não de que o envio falhou).
"""

from __future__ import annotations

from tests._capture import CaptureServer
from tests.test_foundation_privacy import FILE_NAME, RAW, SECRETS

_MASKED_MARKERS = (b"[CPF]", b"[NOME]", b"alertas")


async def _run_analysis(fpool, settings) -> dict:
    from src.foundation.seed import seed_defaults
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    return await analyze(graph, raw_text=RAW, filename=FILE_NAME)


def _assert_capture_is_clean(capture: CaptureServer, where: str) -> bytes:
    blob = capture.blob
    assert blob, f"nenhum payload exportado para {where} — o teste não provou nada"
    low = blob.lower()
    for secret in SECRETS:
        assert secret.lower().encode() not in low, f"{secret!r} vazou no payload de {where}"
    return blob


async def test_nenhum_texto_cru_no_otel_langfuse(fpool, settings, capture, monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{capture.port}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from src.tracing import force_flush, setup_tracing

    setup_tracing("langfuse")
    await _run_analysis(fpool, settings)
    force_flush()

    blob = _assert_capture_is_clean(capture, "Langfuse (OTLP)")
    assert any(marker in blob for marker in _MASKED_MARKERS), (
        "conteúdo mascarado não chegou (trace vazio?)"
    )


async def test_nenhum_texto_cru_no_langsmith(fpool, settings, capture, monkeypatch) -> None:
    """Client explicitamente apontado para o capturador local (nada sai para a nuvem)."""
    import langsmith
    from langsmith import Client

    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_dummy_para_teste")
    client = Client(
        api_url=f"http://127.0.0.1:{capture.port}",
        api_key="lsv2_pt_dummy_para_teste",
        auto_batch_tracing=False,
    )
    langsmith.configure(client=client, enabled=True, project_name="leia-lab-test")

    await _run_analysis(fpool, settings)
    client.flush()

    blob = _assert_capture_is_clean(capture, "LangSmith")
    assert any(marker in blob for marker in (b"[NOME]", b"[CPF]")), (
        "conteúdo mascarado não chegou"
    )
    langsmith.configure(client=None, enabled=None, project_name=None)
