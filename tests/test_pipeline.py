"""Pipeline de relatorios: ordem, classificacao, validacao e falhas parciais."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from src.agent.classifier import CLASSIFIER_EXCERPT_CHARS, classify_minuta
from src.agent.outputs import ChecklistOutput
from src.agent.pipeline import (
    MAX_MINUTA_CHARS,
    EmptyMinutaError,
    MinutaTooLargeError,
    MinutaTypeNotIdentifiedError,
    UnknownMinutaTypeError,
    run_analysis,
)
from src.db.config_repo import MinutaType
from src.db.connection import init_db

MISSING_ID = "00000000-0000-0000-0000-000000000000"


async def _insert_type(pool, name: str = "compra") -> str:
    type_id = await pool.fetchval(
        "INSERT INTO minuta_types (name) VALUES ($1) RETURNING id", name
    )
    return str(type_id)


async def _insert_report(
    pool,
    minuta_type_id,
    *,
    name: str,
    kind: str,
    prompt: str,
    model: str | None = None,
    execution_order: int,
) -> str:
    report_id = await pool.fetchval(
        """
        INSERT INTO minuta_reports
            (minuta_type_id, name, kind, prompt, model, execution_order)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        minuta_type_id,
        name,
        kind,
        prompt,
        model,
        execution_order,
    )
    return str(report_id)


async def _insert_type_with_reports(pool) -> str:
    """Um tipo com parecer e checklist, inseridos fora de ordem."""
    type_id = await _insert_type(pool)
    await _insert_report(
        pool,
        type_id,
        name="checklist-final",
        kind="checklist",
        prompt="Verifique os itens obrigatorios da minuta.",
        execution_order=2,
    )
    await _insert_report(
        pool,
        type_id,
        name="parecer-final",
        kind="parecer",
        prompt="Analise as clausulas de risco da minuta.",
        execution_order=1,
    )
    return type_id


async def test_run_analysis_with_type_runs_reports_in_order(pool, settings):
    await init_db(pool)
    type_id = await _insert_type_with_reports(pool)

    result = await run_analysis(pool, "Contrato de compra", settings, type_id)

    assert result.minuta_type_id == type_id
    assert result.minuta_type_name == "compra"
    assert [item.name for item in result.reports] == ["parecer-final", "checklist-final"]
    assert [item.execution_order for item in result.reports] == [1, 2]
    assert [item.status for item in result.reports] == ["ok", "ok"]

    parecer = result.reports[0]
    assert parecer.kind == "parecer"
    assert parecer.text == "[modo offline] Resultado simulado de parecer-final."
    assert parecer.checklist is None

    checklist = result.reports[1]
    assert checklist.kind == "checklist"
    assert checklist.text is None
    assert isinstance(checklist.checklist, ChecklistOutput)


async def test_run_analysis_without_type_classifies_single_type(pool, settings):
    await init_db(pool)
    type_id = await _insert_type_with_reports(pool)

    result = await run_analysis(pool, "Contrato de compra", settings)

    assert result.minuta_type_id == type_id
    assert [item.status for item in result.reports] == ["ok", "ok"]


async def test_run_analysis_without_registered_types_raises(pool, settings):
    await init_db(pool)

    with pytest.raises(MinutaTypeNotIdentifiedError):
        await run_analysis(pool, "Contrato de compra", settings)


async def test_run_analysis_unknown_type_raises(pool, settings):
    await init_db(pool)
    await _insert_type_with_reports(pool)

    with pytest.raises(UnknownMinutaTypeError):
        await run_analysis(pool, "Contrato de compra", settings, MISSING_ID)


async def test_run_analysis_empty_text_raises(pool, settings):
    await init_db(pool)
    await _insert_type_with_reports(pool)

    with pytest.raises(EmptyMinutaError):
        await run_analysis(pool, "   ", settings)


async def test_run_analysis_too_large_text_raises(pool, settings):
    await init_db(pool)
    await _insert_type_with_reports(pool)

    with pytest.raises(MinutaTooLargeError):
        await run_analysis(pool, "x" * (MAX_MINUTA_CHARS + 1), settings)


async def test_run_analysis_partial_failure_keeps_other_reports(pool, settings, monkeypatch):
    await init_db(pool)
    type_id = await _insert_type_with_reports(pool)

    def boom(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("falha simulada")

    def fake(settings, model_name=None, *, offline_text=None, http_client=None):
        if offline_text is not None and "parecer-final" in offline_text:
            return FunctionModel(boom)
        return TestModel(custom_output_text=offline_text)

    monkeypatch.setattr("src.agent.pipeline.build_model", fake)

    result = await run_analysis(pool, "Contrato de compra", settings, type_id)

    assert [item.status for item in result.reports] == ["failed", "ok"]
    failed = result.reports[0]
    assert failed.name == "parecer-final"
    assert "RuntimeError" in failed.error
    assert result.reports[1].name == "checklist-final"
    assert result.reports[1].status == "ok"


async def test_reports_share_the_cacheable_prefix(pool, settings):
    await init_db(pool)
    type_id = await _insert_type_with_reports(pool)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        content = '{"items": []}' if body.get("response_format") else "ok"
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "total_tokens": 105,
                    "prompt_cache_hit_tokens": 90,
                    "prompt_cache_miss_tokens": 10,
                },
            },
        )

    online = settings.model_copy(
        update={"CHAT_PROVIDER": "deepseek", "CHAT_MODEL": "deepseek-flash", "DEEPSEEK_API_KEY": "fake"}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_analysis(pool, "MINUTA COMPLETA", online, type_id, http_client=client)

    assert [item.status for item in result.reports] == ["ok", "ok"]
    assert bodies[0]["messages"][0] == bodies[1]["messages"][0]
    assert "MINUTA COMPLETA" in bodies[0]["messages"][0]["content"]
    assert bodies[0]["tools"] == bodies[1]["tools"]
    assert result.reports[0].cache_read_tokens == 90


async def test_classifier_reads_only_the_start_of_the_document(settings, monkeypatch):
    seen: list[str] = []

    def fn(messages, info: AgentInfo) -> ModelResponse:
        seen.append(str(messages[0].parts[0].content))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"response": "compra"})])

    monkeypatch.setattr("src.agent.classifier.build_model", lambda *a, **k: FunctionModel(fn))

    found = await classify_minuta(
        "Z" * (CLASSIFIER_EXCERPT_CHARS + 500), [MinutaType(id="1", name="compra")], settings
    )

    assert found is not None
    assert seen[0].count("Z") == CLASSIFIER_EXCERPT_CHARS


async def test_update_on_prompt_applies_to_next_run(pool, settings, monkeypatch):
    await init_db(pool)
    type_id = await _insert_type(pool)
    report_id = await _insert_report(
        pool,
        type_id,
        name="parecer-final",
        kind="parecer",
        prompt="Prompt antigo",
        execution_order=1,
    )

    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(info.instructions or "")])

    monkeypatch.setattr(
        "src.agent.pipeline.build_model",
        lambda *args, **kwargs: FunctionModel(fn),
    )

    first = await run_analysis(pool, "Contrato de compra", settings, type_id)
    await pool.execute(
        "UPDATE minuta_reports SET prompt = $1 WHERE id = $2",
        "Prompt novo",
        report_id,
    )
    second = await run_analysis(pool, "Contrato de compra", settings, type_id)

    assert "Prompt antigo" in first.reports[0].text
    assert "Prompt novo" in second.reports[0].text
