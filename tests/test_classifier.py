"""Classificacao do tipo de minuta: offline, lista vazia e respostas do modelo."""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src.agent.classifier import NONE_LABEL, classify_minuta
from src.db.config_repo import MinutaType

TYPES = [
    MinutaType(id="1", name="Servicos"),
    MinutaType(id="2", name="Locacao"),
]


def _patch_model(monkeypatch, fn) -> None:
    monkeypatch.setattr(
        "src.agent.classifier.build_model", lambda *args, **kwargs: FunctionModel(fn)
    )


async def test_classify_offline_picks_first_type(settings):
    result = await classify_minuta("Contrato de servicos", TYPES, settings)

    assert result == TYPES[0]


async def test_classify_empty_types_returns_none(settings):
    assert await classify_minuta("Contrato", [], settings) is None


async def test_classify_none_label_returns_none(settings, monkeypatch):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"response": NONE_LABEL})]
        )

    _patch_model(monkeypatch, fn)

    assert await classify_minuta("Contrato", TYPES, settings) is None


async def test_classify_returns_matching_type(settings, monkeypatch):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"response": "Locacao"})]
        )

    _patch_model(monkeypatch, fn)

    assert await classify_minuta("Contrato de locacao", TYPES, settings) == TYPES[1]


async def test_classify_returns_none_on_model_error(settings, monkeypatch):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("falha simulada")

    _patch_model(monkeypatch, fn)

    assert await classify_minuta("Contrato", TYPES, settings) is None
