"""M4: rastreio LangSmith sem PII nem segredo, 1 traco por analise, gabarito entre duas versoes."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import httpx
import pytest
import respx

from src.clients.jev import call_jev
from src.config import Settings
from src.db.connection import init_db
from src.db.seed import seed_defaults
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph
from src.tracing import langsmith_tracing, mlflow_tracing, tracing_session
from tests._capture import CaptureServer, capture  # noqa: F401 - fixture
from tests.conftest import TEST_DATABASE_URL
from tests.test_trail_privacy import FILE_NAME, RAW, SECRETS


@pytest.fixture
async def seeded(pool):
    await init_db(pool)
    await seed_defaults(pool)
    return pool


async def _traced_analysis(pool, settings, cap: CaptureServer, n: int = 1) -> list[dict]:
    graph = build_analyze_minuta_graph(pool, settings)
    with langsmith_tracing(client=cap.client, project_name="leia-lab-teste"):
        return [await analyze(graph, raw_text=RAW, filename=FILE_NAME) for _ in range(n)]


async def test_trace_payload_has_masked_text_and_no_personal_data(seeded, settings, capture):
    outs = await _traced_analysis(seeded, settings, capture)
    blob = capture.blob.lower()
    assert blob, "nada foi exportado: o teste nao provaria nada"
    leaked = [s for s in SECRETS if s.lower().encode() in blob]
    assert leaked == []
    assert b"[nome]" in blob and b"[cpf]" in blob  # o texto mascarado esta la, visivel para depurar
    assert outs[0]["filename"].lower().encode() in blob  # o apelido do arquivo vai como metadado
    assert b"analisar_minuta" in blob and b"call_jev" in blob and b"chat_completion" in blob


async def test_trace_never_carries_settings_secrets(seeded, settings, capture):
    db_password = urlsplit(TEST_DATABASE_URL).password
    await _traced_analysis(seeded, settings, capture)
    assert db_password and db_password.encode() not in capture.blob
    assert b"DATABASE_URL" not in capture.blob and b"TYPESAFE_API_KEY" not in capture.blob


@respx.mock
async def test_api_keys_never_reach_the_trace_on_a_real_client_call(capture):
    s = Settings(TYPESAFE_API_KEY="sk-SEGREDO-DO-JEV", TYPESAFE_BASE_URL="https://jev.invalid/v1/systemone")
    respx.post(s.TYPESAFE_BASE_URL).mock(return_value=httpx.Response(200, json={"answers": {"q": {"noul": 0.9}}}))
    with langsmith_tracing(client=capture.client, project_name="leia-lab-teste"):
        await call_jev({"clausula": "texto [NOME]"}, {"q": {"type": "noul", "instructions": "?"}}, s)
    assert b"[NOME]" in capture.blob and b"call_jev" in capture.blob
    assert b"SEGREDO" not in capture.blob


async def test_one_trace_per_analysis_with_every_call_inside_it(seeded, settings, capture):
    """A LangSmith cobra por traco (arvore inteira): N analises tem de ser N tracos, nao N x chamadas."""
    await _traced_analysis(seeded, settings, capture, n=2)
    assert len(capture.trace_ids()) == 2
    assert capture.blob.count(b'"name":"call_jev"') + capture.blob.count(b'"name": "call_jev"') > 2


def test_tracing_refuses_to_start_without_an_api_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"), langsmith_tracing():
        pass


async def test_dual_tracing_sends_masked_nested_traces_to_both_backends(seeded, settings, capture):
    db_password = urlsplit(TEST_DATABASE_URL).password
    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    with tracing_session(
        langsmith_client=capture.client,
        langsmith_project="leia-lab-teste",
        mlflow_uri=capture.mlflow_uri,
        mlflow_experiment="leia-lab-teste",
    ) as active:
        assert active["langsmith"] is capture.client and active["mlflow"] == capture.mlflow_uri
        outs = [await analyze(graph, raw_text=RAW, filename=FILE_NAME)]

    for blob in (capture.blob.lower(), capture.mlflow_blob.lower()):
        assert blob, "ambos os backends precisam receber payload"
        assert [s for s in SECRETS if s.lower().encode() in blob] == []
        assert b"[nome]" in blob and b"[cpf]" in blob
        assert outs[0]["filename"].lower().encode() in blob
        assert b"analisar_minuta" in blob and b"call_jev" in blob and b"chat_completion" in blob
        assert db_password and db_password.encode() not in blob
        assert b"database_url" not in blob and b"typesafe_api_key" not in blob

    assert len(capture.trace_ids()) == 1
    assert len(capture.mlflow_trace_ids()) == 1
    # o traco MLflow fica amarrado a analise: a tag leia.analysis_id carrega o id devolvido pelo CLI
    aid = outs[0]["analysis_id"].encode()
    tag_pos = capture.mlflow_blob.find(b"leia.analysis_id")
    assert tag_pos != -1 and aid in capture.mlflow_blob[tag_pos : tag_pos + 120]
    otlp_trace_ids = {sp["traceId"] for sp in capture.mlflow_spans}
    assert len(otlp_trace_ids) == 1
    jev_spans = [sp for sp in capture.mlflow_spans if sp.get("name") == "call_jev"]
    assert len(jev_spans) > 1 and all(sp.get("parentSpanId") for sp in jev_spans)


@respx.mock
async def test_tracing_session_works_with_mlflow_only_and_enforces_allowlist(capture, monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", capture.mlflow_uri)
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "leia-lab-teste")
    s = Settings(TYPESAFE_API_KEY="sk-SEGREDO-DO-JEV", TYPESAFE_BASE_URL="https://jev.invalid/v1/systemone")
    respx.post(s.TYPESAFE_BASE_URL).mock(return_value=httpx.Response(200, json={"answers": {"q": {"noul": 0.9}}}))
    with tracing_session() as active:
        assert active["langsmith"] is None and active["mlflow"] == capture.mlflow_uri
        await call_jev({"clausula": "texto [NOME]"}, {"q": {"type": "noul", "instructions": "?"}}, s)
    assert capture.blob == b""
    assert b"[NOME]" in capture.mlflow_blob and b"call_jev" in capture.mlflow_blob
    assert b"SEGREDO" not in capture.mlflow_blob and b"TYPESAFE_API_KEY" not in capture.mlflow_blob


def test_tracing_session_refuses_to_start_when_no_backend_is_configured(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"), tracing_session():
        pass


@respx.mock
async def test_mlflow_tracing_does_not_leak_after_context_exit(capture, monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    s = Settings(TYPESAFE_API_KEY="", TYPESAFE_BASE_URL="https://jev.invalid/v1/systemone")
    with mlflow_tracing(tracking_uri=capture.mlflow_uri, experiment_name="leia-lab-teste"):
        await call_jev({"clausula": "texto [NOME]"}, {"q": {"type": "noul", "instructions": "?"}}, s)
    assert capture.mlflow_bodies
    capture.mlflow_bodies.clear()
    await call_jev({"clausula": "texto [NOME]"}, {"q": {"type": "noul", "instructions": "?"}}, s)
    assert capture.mlflow_bodies == []


# ---------------------------------------------------------------- consulta pelo analysis_id


def test_find_trace_devolve_none_com_mlflow_fora_do_ar():
    """O admin tem de renderizar com o MLflow caido: falha de rede vira None, nunca excecao."""
    from src.tracing import find_trace

    dead = "http://127.0.0.1:1"  # nada escuta na porta 1: conexao recusada
    assert find_trace(dead, "leia-lab", uuid.uuid4()) is None


def test_find_trace_sem_uri_devolve_none():
    from src.tracing import find_trace

    assert find_trace("", "leia-lab", uuid.uuid4()) is None


async def test_find_trace_acha_o_traco_tagueado_na_captura(seeded, settings, capture):
    """Contra o servidor de captura: o traco gravado numa analise e achavel pelo analysis_id."""
    from src.tracing import find_trace

    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    with mlflow_tracing(tracking_uri=capture.mlflow_uri, experiment_name="leia-lab-teste"):
        out = await analyze(graph, raw_text=RAW, filename=FILE_NAME)
    ref = find_trace(capture.mlflow_uri, "leia-lab-teste", uuid.UUID(out["analysis_id"]))
    assert ref is not None
    assert ref.experiment_id == "42"  # o que o servidor de captura devolve em get-by-name
    assert ref.trace_id.startswith("tr-")
    assert ref.duration_ms is not None and ref.duration_ms >= 0


# ---------------------------------------------------------------- gabarito no CLI


@pytest.mark.skipif(not os.environ.get("LEIA_MINUTAS_DIR"), reason="minutas mascaradas locais nao configuradas")
async def test_gold_run_compares_two_matrix_versions(seeded, settings):
    from src.cli import gold_compare, gold_run
    from src.eval.gold import minutas_dir

    v1 = await gold_run(seeded, settings, minutas_dir())
    await seeded.execute("UPDATE risk_matrix SET active = false WHERE risk_id = 'R-04'")  # matriz v2
    v2 = await gold_run(seeded, settings, minutas_dir())

    assert v1["matrix_version"] != v2["matrix_version"] and v1["prompt_version"] == v2["prompt_version"]
    cmp = await gold_compare(seeded, v1["analyses"], v2["analyses"])
    assert cmp["b"]["fp"] < cmp["a"]["fp"]  # o Jev offline marca R-04 em toda clausula; tira-lo remove esses FP
    assert cmp["changed_clauses"] and set(cmp["delta"]) == {"precision", "recall", "f1"}
    # a rodada antiga, re-pontuada depois da mudanca, continua igual: vem de analyses, nao da matriz atual
    assert (await gold_compare(seeded, v1["analyses"], v1["analyses"]))["a"] == v1["score"]


# ---------------------------------------------------------------- limite do plano (M6)


class _FakeRuns:
    def __init__(self, n: int) -> None:
        self.n, self.calls = n, []

    def list_runs(self, **kw):
        self.calls.append(kw)
        return iter(range(self.n))


@pytest.mark.parametrize(("n", "status"), [(10, "ok"), (4000, "alerta"), (5000, "estourado")])
def test_trace_usage_counts_root_runs_of_the_month(n, status):
    import datetime as dt

    from src.tracing import trace_usage

    fake = _FakeRuns(n)
    res = trace_usage(fake, "leia-lab", limit=5000, now=dt.datetime(2026, 11, 16, 15, 30, tzinfo=dt.UTC))
    assert (res["traces"], res["status"], res["since"]) == (n, status, "2026-11-01")
    call = fake.calls[0]
    assert call["is_root"] is True and call["project_name"] == "leia-lab"  # 1 traco = 1 raiz = 1 analise
    assert call["start_time"] == dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
