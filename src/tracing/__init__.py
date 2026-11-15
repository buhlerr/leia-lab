"""Instrumentação do protótipo B3: liga o grafo da F às ferramentas de registro.

``setup_tracing(tool)`` com ``tool`` em ``off|langsmith|langfuse|phoenix`` (flag
``--trace`` do CLI). LangSmith é só env vars (langchain-core instrumenta o grafo
nativamente); Langfuse Cloud e Phoenix (self-hosted no CT 116) recebem spans via
OpenTelemetry/OTLP http. Os clientes LLM (httpx cru) emitem spans manuais com as
convenções openinference — só conteúdo mascarado entra nesses atributos.
"""

from __future__ import annotations

import base64
import os

TOOLS = ("off", "langsmith", "langfuse", "phoenix")

_PROVIDER = None  # TracerProvider ativo (force_flush nos testes/encerramento)


def setup_tracing(tool: str) -> str | None:
    """Liga a instrumentação; devolve descrição curta (``None`` = off)."""
    if tool == "off":
        return None
    if tool == "langsmith":
        os.environ["LANGSMITH_TRACING"] = "true"
        project = os.environ.get("LANGSMITH_PROJECT")
        return f"langsmith: tracing on (project={project or '(default)'})"
    if tool == "langfuse":
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
        if not (pk and sk):
            raise RuntimeError("LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY ausentes (variáveis de usuário)")
        endpoint = f"{host}/api/public/otel/v1/traces"
        auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        return _otel(endpoint, {"Authorization": f"Basic {auth}"}, f"langfuse -> {host}")
    if tool == "phoenix":
        base = os.environ.get("PHOENIX_ENDPOINT", "http://192.168.0.120:4318").rstrip("/")
        return _otel(f"{base}/v1/traces", None, f"phoenix -> {base}")
    raise ValueError(f"ferramenta de tracing desconhecida: {tool!r}")


def _otel(endpoint: str, headers: dict[str, str] | None, label: str) -> str:
    global _PROVIDER
    from opentelemetry import trace as ot_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "leia-analyze"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    ot_trace.set_tracer_provider(provider)
    from openinference.instrumentation.langchain import LangChainInstrumentor

    LangChainInstrumentor().instrument()
    _PROVIDER = provider
    return label


def force_flush(timeout_millis: int = 30000) -> None:
    """Exporta spans pendentes (testes e encerramento)."""
    if _PROVIDER is not None:
        _PROVIDER.force_flush(timeout_millis)
