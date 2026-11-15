import json

import httpx
import respx

from src.clients.jev import call_jev
from src.clients.llm import chat_completion
from src.config import Settings


async def test_call_jev_offline_fallback_returns_deterministic_answers():
    settings = Settings(TYPESAFE_API_KEY="", OPENROUTER_API_KEY="")
    questions = {
        "tipo": {
            "type": "choice",
            "instructions": "Qual o tipo?",
            "criteria": {"locacao_residencial": "Locacao", "nao_suportado": "Outro"},
        },
        "risco": {
            "type": "noul",
            "instructions": "Tem risco?",
            "criteria": {"true": "Sim", "false": "Nao"},
        },
    }
    res = await call_jev({"inicio": "CONTRATO DE LOCAÇÃO RESIDENCIAL"}, questions, settings)
    assert "answers" in res
    assert res["answers"]["tipo"]["choice"] == "locacao_residencial"
    assert isinstance(res["answers"]["risco"]["noul"], float)
    assert "usage" in res and "input_tokens" in res["usage"]


@respx.mock
async def test_call_jev_retries_on_429_and_parses_response():
    settings = Settings(
        TYPESAFE_API_KEY="ts-test-key",
        TYPESAFE_BASE_URL="https://api.typesafe.ai/v1/systemone",
        JEV_MODEL="jev-1.14.0",
    )
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate_limit"}),
            httpx.Response(
                200,
                json={
                    "answers": {"tipo": {"choice": "locacao_residencial", "confidence": 0.96}},
                    "usage": {"input_tokens": 42},
                },
            ),
        ]
    )
    res = await call_jev(
        {"inicio": "Contrato"},
        {"tipo": {"type": "choice", "instructions": "?", "criteria": {"locacao_residencial": "A"}}},
        settings,
    )
    assert route.call_count == 2
    assert res["answers"]["tipo"]["choice"] == "locacao_residencial"
    assert res["usage"]["input_tokens"] == 42


@respx.mock
async def test_chat_completion_calls_openrouter_and_offline_fallback():
    offline_settings = Settings(OPENROUTER_API_KEY="")
    text, tokens = await chat_completion("sys", "Pergunta: qual o prazo?", offline_settings)
    assert isinstance(text, str) and len(text) > 0
    assert tokens == 0

    online_settings = Settings(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        CHAT_MODEL="openai/gpt-4o-mini",
    )
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"alertas": []}'}}],
                "usage": {"total_tokens": 55},
            },
        )
    )
    content, used = await chat_completion("sys", "user", online_settings)
    assert content == '{"alertas": []}'
    assert used == 55


async def test_chat_completion_offline_alertas_parses_risks_and_clause():
    settings = Settings(OPENROUTER_API_KEY="")
    user = "Riscos:\n- R-01: Reajuste semestral\n- R-02: Multa abusiva\n<clausula>Cláusula 2ª - reajuste.</clausula>"
    text, tokens = await chat_completion('responda JSON "alertas"', user, settings)
    data = json.loads(text)
    assert tokens == 0
    assert [a["id"] for a in data["alertas"]] == ["R-01", "R-02"]
    assert data["alertas"][0]["resumo"] == "Reajuste semestral"
    assert data["alertas"][0]["trecho"] == "Cláusula 2ª - reajuste."
    assert data["alertas"][0]["discorda"] is False


async def test_call_jev_offline_non_locacao_is_nao_suportado():
    settings = Settings(TYPESAFE_API_KEY="")
    q = {"tipo": {"type": "choice", "instructions": "?", "criteria": {"locacao_residencial": "A", "nao_suportado": "B"}}}
    res = await call_jev({"inicio": "ATA DE ASSEMBLEIA"}, q, settings)
    assert res["answers"]["tipo"]["choice"] == "nao_suportado"
