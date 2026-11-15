"""Prova empirica (B3): nada de texto cru sai do processo para os colecionadores.

Um servidor HTTP local captura os payloads brutos (OTLP/protobuf do Langfuse e
Phoenix; JSON do LangSmith com LANGSMITH_ENDPOINT sobreposto). PII conhecida
da minuta sintetica NAO pode aparecer; o conteudo mascarado tem de aparecer
(prova de que o trace real foi capturado, nao de que o envio falhou).
"""

from __future__ import annotations

import gzip
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.test_foundation_privacy import FILE_NAME, RAW, SECRETS

_MASKED_MARKERS = (b"[CPF]", b"[NOME]", b"alertas")


class _CaptureServer:
    """Captura todos os corpos de requisicao (decomprimindo gzip)."""

    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - API do http.server
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                outer.bodies.append(body)
                payload = b'{"id": "00000000-0000-0000-0000-000000000000"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def blob(self) -> bytes:
        return b"\n".join(self.bodies)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def capture() -> Iterator[_CaptureServer]:
    server = _CaptureServer()
    yield server
    server.stop()


async def _run_analysis(fpool, settings) -> dict:
    from src.foundation.seed import seed_defaults
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    await seed_defaults(fpool)
    graph = build_analyze_minuta_graph(fpool, settings)
    return await analyze(graph, raw_text=RAW, filename=FILE_NAME)


async def test_nenhum_texto_cru_no_otel_langfuse(fpool, settings, capture, monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{capture.port}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from src.tracing import force_flush, setup_tracing

    setup_tracing("langfuse")
    out = await _run_analysis(fpool, settings)
    force_flush()

    blob = capture.blob
    assert blob, "nenhum payload exportado — o capturador falhou, nao o sigilo"
    low = blob.lower()
    for secret in SECRETS:
        assert secret.lower().encode() not in low, f"{secret!r} vazou no payload OTLP"
    assert any(m in blob for m in _MASKED_MARKERS), "conteudo mascarado nao chegou (trace vazio?)"


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

    out = await _run_analysis(fpool, settings)
    client.flush()

    blob = capture.blob
    assert blob, "nenhum payload enviado ao endpoint local — o teste nao provou nada"
    low = blob.lower()
    for secret in SECRETS:
        assert secret.lower().encode() not in low, f"{secret!r} vazou no payload do LangSmith"
    assert any(m in blob for m in (b"[NOME]", b"[CPF]")), "conteudo mascarado nao chegou"
    langsmith.configure(client=None, enabled=None, project_name=None)
