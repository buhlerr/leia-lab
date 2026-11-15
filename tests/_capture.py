"""Servidor HTTP local que captura payloads de telemetria (fixture `capture`)."""

from __future__ import annotations

import gzip
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class CaptureServer:
    """Captura todos os corpos de requisição (decomprimindo gzip)."""

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
def capture() -> Iterator[CaptureServer]:
    server = CaptureServer()
    yield server
    # fecha o provider OTel antes do servidor: nada exporta para uma porta morta
    from src.tracing import shutdown

    shutdown()
    server.stop()
