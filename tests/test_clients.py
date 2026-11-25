import json

import httpx
import respx

from src.clients.jev import call_jev
from src.clients.llm import ChatResult, chat_completion
from src.config import Settings
from src.ingest.masking import mask_payload, mask_personal_data


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
    res = await call_jev(*mask_payload(({"inicio": "CONTRATO DE LOCAÇÃO RESIDENCIAL"}, questions)), settings)
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
        mask_payload({"inicio": "Contrato"}),
        mask_payload({"tipo": {"type": "choice", "instructions": "?", "criteria": {"locacao_residencial": "A"}}}),
        settings,
    )
    # O 429 nao vira erro: o chamador recebe a resposta da tentativa seguinte.
    assert res["answers"]["tipo"]["choice"] == "locacao_residencial"
    assert res["usage"]["input_tokens"] == 42
    # O servidor viu a MESMA pergunta na retentativa -- e so ela: um terceiro
    # pedido esgotaria o script do mock e derrubaria o teste.
    pedidos = [c.request for c in route.calls]
    assert len(pedidos) == 2
    assert pedidos[0].content == pedidos[1].content


@respx.mock
async def test_chat_completion_sends_limits_and_data_policy_and_parses_cost():
    offline_settings = Settings(OPENROUTER_API_KEY="")
    res = await chat_completion("sys", mask_personal_data("Pergunta: qual o prazo?"), offline_settings)
    assert isinstance(res, ChatResult)
    assert isinstance(res.text, str) and len(res.text) > 0
    assert (res.tokens, res.cost_usd) == (0, 0.0)  # offline nao gasta nada

    online_settings = Settings(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        CHAT_MODEL="deepseek/deepseek-v4.1-flash",
        CHAT_MAX_TOKENS=1500,
    )
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"alertas": []}'}}],
                "usage": {"total_tokens": 55, "cost": 0.0123},
            },
        )
    )
    r = await chat_completion("sys", mask_personal_data("user"), online_settings)
    assert (r.text, r.tokens, r.cost_usd) == ('{"alertas": []}', 55, 0.0123)

    payload = json.loads(route.calls.last.request.content)
    assert payload["provider"] == {"data_collection": "deny"}
    assert payload["usage"] == {"include": True}
    assert payload["max_tokens"] == 1500  # default: CHAT_MAX_TOKENS, sem max_tokens explicito
    assert payload["reasoning"] == {"enabled": False}
    assert "response_format" not in payload

    await chat_completion("sys", mask_personal_data("user"), online_settings, json_output=True)
    payload = json.loads(route.calls.last.request.content)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["provider"]["require_parameters"] is True  # so provedores que aceitam JSON mode
    assert payload["reasoning"] == {"enabled": False}


@respx.mock
async def test_chat_completion_retries_without_reasoning_when_model_rejects_parameter():
    settings = Settings(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1",
        CHAT_MODEL="openai/gpt-4o-mini",
    )
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(404, json={"error": {"message": "No endpoints found that can handle the requested parameters."}}),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"alertas": []}'}}],
                    "usage": {"total_tokens": 30, "cost": 0.001},
                },
            ),
        ]
    )
    res = await chat_completion("sys", mask_personal_data("user"), settings, json_output=True)
    assert res.text == '{"alertas": []}'
    assert len(route.calls) == 2
    assert "reasoning" in json.loads(route.calls[0].request.content)
    assert "reasoning" not in json.loads(route.calls[1].request.content)


async def test_chat_completion_offline_alertas_parses_risks_and_clause():
    settings = Settings(OPENROUTER_API_KEY="")
    user = "Riscos:\n- R-01: Reajuste semestral\n- R-02: Multa abusiva\n<clausula>Cláusula 2ª - reajuste.</clausula>"
    res = await chat_completion('responda JSON "alertas"', mask_personal_data(user), settings)
    data = json.loads(res.text)
    assert (res.tokens, res.cost_usd) == (0, 0.0)
    assert [a["id"] for a in data["alertas"]] == ["R-01", "R-02"]
    assert data["alertas"][0]["resumo"] == "Reajuste semestral"
    assert data["alertas"][0]["trecho"] == "Cláusula 2ª - reajuste."
    assert data["alertas"][0]["discorda"] is False


async def test_call_jev_offline_non_locacao_is_nao_suportado():
    settings = Settings(TYPESAFE_API_KEY="")
    q = {"tipo": {"type": "choice", "instructions": "?", "criteria": {"locacao_residencial": "A", "nao_suportado": "B"}}}
    res = await call_jev(*mask_payload(({"inicio": "ATA DE ASSEMBLEIA"}, q)), settings)
    assert res["answers"]["tipo"]["choice"] == "nao_suportado"
