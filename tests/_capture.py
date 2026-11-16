"""Servidor HTTP local que faz o papel da LangSmith e guarda os payloads (fixture ``capture``)."""

from __future__ import annotations

import gzip
import re
import threading
from collections.abc import Iterator

import pytest
from langsmith import Client

_TRACE_ID = re.compile(rb'"trace_id":\s*"([0-9a-f-]{36})"')


class CaptureServer:
    def __init__(self) -> None:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        self.bodies: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                    body = gzip.decompress(body)
                if self.command != "GET":
                    outer.bodies.append(body)
                payload = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PATCH = _handle

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.client = Client(api_url=f"http://127.0.0.1:{self._server.server_address[1]}", api_key="lsv2_pt_teste")
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def blob(self) -> bytes:
        return b"\n".join(self.bodies)

    def trace_ids(self) -> set[bytes]:
        return set(_TRACE_ID.findall(self.blob))

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def capture() -> Iterator[CaptureServer]:
    server = CaptureServer()
    yield server
    server.stop()
