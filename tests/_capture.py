"""Servidor HTTP local que faz o papel da LangSmith e da MLflow (fixture ``capture``)."""

from __future__ import annotations

import gzip
import json
import re
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from google.protobuf.json_format import MessageToDict, MessageToJson
from langsmith import Client
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

_TRACE_ID = re.compile(rb'"trace_id":\s*"([0-9a-f-]{36})"')
_MLFLOW_TRACE_ID = re.compile(rb'"trace_id":\s*"(tr-[0-9a-f]+)"')


class CaptureServer:
    def __init__(self) -> None:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        self.bodies: list[bytes] = []
        self.mlflow_bodies: list[bytes] = []
        self.mlflow_spans: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                    body = gzip.decompress(body)
                parsed = urlsplit(self.path)
                path = parsed.path

                ctype = "application/json"
                payload = b"{}"

                if path == "/version":
                    ctype = "text/plain"
                    payload = b"3.18.0"
                elif path == "/api/2.0/mlflow/experiments/get-by-name":
                    exp_name = parse_qs(parsed.query).get("experiment_name", ["leia-lab"])[0]
                    payload = json.dumps(
                        {
                            "experiment": {
                                "experiment_id": "42",
                                "name": exp_name,
                                "artifact_location": "mlflow-artifacts:/42",
                                "lifecycle_stage": "active",
                            }
                        }
                    ).encode()
                elif path == "/api/3.0/mlflow/traces" and self.command == "POST":
                    outer.mlflow_bodies.append(body)
                    req = json.loads(body)
                    ti = req["trace"]["trace_info"]
                    ti.setdefault("tags", {})["mlflow.trace.spansLocation"] = "TRACKING_STORE"
                    payload = json.dumps({"trace": {"trace_info": ti}}).encode()
                elif path == "/v1/traces" and self.command == "POST":
                    otlp = ExportTraceServiceRequest()
                    otlp.ParseFromString(body)
                    outer.mlflow_bodies.append(MessageToJson(otlp).encode("utf-8"))
                    otlp_dict = MessageToDict(otlp)
                    for rs in otlp_dict.get("resourceSpans", []):
                        for ss in rs.get("scopeSpans", []):
                            outer.mlflow_spans.extend(ss.get("spans", []))
                    ctype = "application/x-protobuf"
                    payload = ExportTraceServiceResponse().SerializeToString()
                elif path.startswith(("/api/2.0/mlflow", "/api/3.0/mlflow")):
                    if self.command != "GET":
                        outer.mlflow_bodies.append(body)
                elif self.command != "GET":
                    outer.bodies.append(body)

                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PATCH = do_PUT = _handle

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self.client = Client(api_url=base_url, api_key="lsv2_pt_teste")
        self.mlflow_uri = base_url
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def blob(self) -> bytes:
        return b"\n".join(self.bodies)

    @property
    def mlflow_blob(self) -> bytes:
        return b"\n".join(self.mlflow_bodies)

    def trace_ids(self) -> set[bytes]:
        return set(_TRACE_ID.findall(self.blob))

    def mlflow_trace_ids(self) -> set[bytes]:
        return set(_MLFLOW_TRACE_ID.findall(self.mlflow_blob))

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def capture() -> Iterator[CaptureServer]:
    server = CaptureServer()
    yield server
    server.stop()
