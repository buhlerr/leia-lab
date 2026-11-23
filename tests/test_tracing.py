"""M4: rastreio LangSmith sem PII nem segredo, 1 traco por analise, gabarito entre duas versoes."""

from __future__ import annotations

import asyncio
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
from src.ingest.masking import mask_payload
from src.tracing import langsmith_tracing, mlflow_tracing, tracing_session
from tests._capture import CaptureServer, capture  # noqa: F401 - fixture
from tests.conftest import TEST_DATABASE_URL
from tests.test_trail_privacy import FILE_NAME, RAW, SECRETS

JEV_ARGS = mask_payload(({"clausula": "texto [NOME]"}, {"q": {"type": "noul", "instructions": "?"}}))


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
        await call_jev(*JEV_ARGS, s)
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
        await call_jev(*JEV_ARGS, s)
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
        await call_jev(*JEV_ARGS, s)
    assert capture.mlflow_bodies
    capture.mlflow_bodies.clear()
    await call_jev(*JEV_ARGS, s)
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


# ---------------------------------------------------------------- rastreio que falha nunca derruba


class _MlflowDown(Exception):
    pass


def _raise_mlflow_down(calls: list[str], name: str):
    def boom(*args, **kwargs):
        calls.append(name)
        raise _MlflowDown(name)

    return boom


async def test_analysis_finishes_and_tracing_turns_off_when_mlflow_raises_mid_run(seeded, settings, capture, monkeypatch):
    import mlflow

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    calls: list[str] = []
    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    with tracing_session(mlflow_uri=capture.mlflow_uri, mlflow_experiment="leia-lab-teste"):
        monkeypatch.setattr(mlflow, "start_span", _raise_mlflow_down(calls, "start_span"))
        monkeypatch.setattr(mlflow, "update_current_trace", _raise_mlflow_down(calls, "update_current_trace"))
        out = await analyze(graph, raw_text=RAW, filename=FILE_NAME)

    assert await seeded.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", out["analysis_id"]) == "done"
    assert len(calls) == 1, f"depois da primeira falha o rastreio fica desligado; chamadas: {calls}"


async def test_analysis_runs_untraced_when_mlflow_setup_raises_and_process_state_is_restored(
    seeded, settings, capture, monkeypatch
):
    import mlflow
    from mlflow.tracing.provider import is_tracing_enabled

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    prev_uri = mlflow.get_tracking_uri()
    mlflow.tracing.disable()
    calls: list[str] = []
    monkeypatch.setattr(mlflow, "set_experiment", _raise_mlflow_down(calls, "set_experiment"))
    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    try:
        with tracing_session(mlflow_uri=capture.mlflow_uri, mlflow_experiment="leia-lab-teste"):
            out = await analyze(graph, raw_text=RAW, filename=FILE_NAME)
        assert calls == ["set_experiment"]
        assert await seeded.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", out["analysis_id"]) == "done"
        assert not is_tracing_enabled(), "o enable do MLflow precisa ser desfeito"
        assert mlflow.get_tracking_uri() == prev_uri
        assert "MLFLOW_TRACKING_URI" not in os.environ
    finally:
        mlflow.tracing.reset()


def _probe_mlflow_calls(monkeypatch, calls: list[str], failing: str) -> None:
    """Grava cada chamada que ``client_span``/``tag_span`` fazem ao MLflow; ``failing`` levanta.

    O autolog do LangChain chama as mesmas funcoes por conta propria: so conta quem vem de
    ``src.tracing``.
    """
    import sys

    import mlflow
    from mlflow.entities import LiveSpan

    def probe(name, real, *, any_caller=False):
        def call(*args, **kwargs):
            if not any_caller and sys._getframe(1).f_globals.get("__name__") != "src.tracing":
                return real(*args, **kwargs)
            calls.append(name)
            if name == failing:
                raise _MlflowDown(name)
            return real(*args, **kwargs)

        return call

    real_start = mlflow.start_span

    class _Span:
        def __init__(self, *args, **kwargs):
            self.cm = real_start(*args, **kwargs)

        def __enter__(self):
            return self.cm.__enter__()

        def __exit__(self, *exc):
            return probe("exit", self.cm.__exit__, any_caller=True)(*exc)

    monkeypatch.setattr(mlflow, "start_span", probe("start_span", _Span))
    monkeypatch.setattr(LiveSpan, "set_inputs", probe("set_inputs", LiveSpan.set_inputs))
    monkeypatch.setattr(LiveSpan, "set_outputs", probe("set_outputs", LiveSpan.set_outputs))
    monkeypatch.setattr(mlflow, "get_current_active_span", probe("tag_span", mlflow.get_current_active_span))


@pytest.mark.parametrize("failing", ["start_span", "set_inputs", "tag_span", "set_outputs", "exit"])
async def test_mlflow_failing_inside_a_client_span_turns_tracing_off_and_the_analysis_finishes(
    seeded, settings, capture, monkeypatch, failing
):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    calls: list[str] = []
    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    with tracing_session(mlflow_uri=capture.mlflow_uri, mlflow_experiment="leia-lab-teste"):
        _probe_mlflow_calls(monkeypatch, calls, failing)
        out = await analyze(graph, raw_text=RAW, filename=FILE_NAME)

    assert await seeded.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", out["analysis_id"]) == "done"
    assert calls.count(failing) == 1, calls
    after = calls[calls.index(failing) + 1 :]
    assert after in ([], ["exit"]), f"depois da falha so o span aberto e fechado; chamadas: {calls}"


async def test_mlflow_restores_the_env_uri_even_when_set_tracking_uri_raises_on_exit(capture, monkeypatch):
    import mlflow

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    real = mlflow.set_tracking_uri
    calls: list[str] = []

    def set_uri_then_fail(uri):
        calls.append("set_tracking_uri")
        if len(calls) > 1:
            raise _MlflowDown("set_tracking_uri")
        real(uri)

    monkeypatch.setattr(mlflow, "set_tracking_uri", set_uri_then_fail)
    try:
        with mlflow_tracing(tracking_uri=capture.mlflow_uri, experiment_name="leia-lab-teste"):
            assert os.environ.get("MLFLOW_TRACKING_URI") == capture.mlflow_uri
        assert calls == ["set_tracking_uri", "set_tracking_uri"]
        assert "MLFLOW_TRACKING_URI" not in os.environ
    finally:
        real(None)
        mlflow.tracing.reset()


@pytest.fixture
def langsmith_env(monkeypatch):
    """Variaveis da LangSmith lidas de novo: o SDK guarda cada uma em cache no processo."""
    from langsmith import utils

    utils.get_env_var.cache_clear()
    yield monkeypatch
    monkeypatch.undo()
    utils.get_env_var.cache_clear()


async def test_analysis_runs_untraced_when_the_langsmith_env_breaks_the_client(seeded, settings, langsmith_env):
    langsmith_env.delenv("MLFLOW_TRACKING_URI", raising=False)
    langsmith_env.setenv("LANGSMITH_API_KEY", "lsv2-falsa")
    langsmith_env.setenv("LANGSMITH_TRACING_MODE", "modo-invalido")  # Client() levanta LangSmithUserError
    graph = build_analyze_minuta_graph(pool=seeded, settings=settings)
    with tracing_session() as active:
        out = await analyze(graph, raw_text=RAW, filename=FILE_NAME)
    assert active["langsmith"] is None
    assert await seeded.fetchval("SELECT status FROM analyses WHERE id = $1::uuid", out["analysis_id"]) == "done"


@respx.mock
async def test_client_call_returns_its_result_when_the_langsmith_env_breaks_the_run(capture, langsmith_env):
    langsmith_env.setenv("LANGSMITH_ENDPOINT", "http://127.0.0.1:1")
    langsmith_env.setenv("LANGSMITH_RUNS_ENDPOINTS", '{"http://127.0.0.1:2": "lsv2-falsa"}')  # RunTree() levanta
    s = Settings(TYPESAFE_API_KEY="sk-teste", TYPESAFE_BASE_URL="https://jev.invalid/v1/systemone")
    respx.post(s.TYPESAFE_BASE_URL).mock(return_value=httpx.Response(200, json={"answers": {"q": {"noul": 0.9}}}))
    with langsmith_tracing(client=capture.client, project_name="leia-lab-teste"):
        out = await call_jev(*JEV_ARGS, s)
    assert out["answers"] == {"q": {"noul": 0.9}}


class _BusinessError(Exception):
    pass


@pytest.mark.parametrize("error", [_BusinessError("regra"), asyncio.CancelledError()])
async def test_client_span_lets_errors_of_the_wrapped_call_through_untouched(capture, monkeypatch, error):
    from src.tracing import client_span

    @client_span("chamada", allowed=("x",))
    async def fails(x):
        raise error

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with (
        tracing_session(
            langsmith_client=capture.client,
            langsmith_project="leia-lab-teste",
            mlflow_uri=capture.mlflow_uri,
            mlflow_experiment="leia-lab-teste",
        ),
        pytest.raises(type(error)) as raised,
    ):
        await fails(1)
    assert raised.value is error
