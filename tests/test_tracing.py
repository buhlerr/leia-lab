"""M4: rastreio LangSmith sem PII nem segredo, 1 traco por analise, gabarito entre duas versoes."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx
import pytest
import respx

from src.clients.jev import call_jev
from src.config import Settings
from src.db.connection import init_db
from src.db.seed import seed_defaults
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph
from src.tracing import langsmith_tracing
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
