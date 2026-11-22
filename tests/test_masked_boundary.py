"""Fronteira de privacidade: toda funcao que manda texto para fora do processo ou o grava recusa str comum."""

from __future__ import annotations

import re

import pytest

from src.clients.jev import call_jev
from src.clients.llm import chat_completion
from src.config import Settings
from src.db.analyses import start_analysis
from src.ingest.masking import UnmaskedTextError, mask_payload, mask_personal_data, resolve_doc_alias
from src.rag.embeddings import embed_text
from src.tracing import tracing_session
from tests._capture import capture  # noqa: F401 - fixture

NAME = "Carlos Eduardo Mendes"
CPF = "999.888.777-66"
RAW = f"LOCADOR: {NAME}, brasileiro, CPF {CPF}."
OFFLINE = Settings(OPENROUTER_API_KEY="", TYPESAFE_API_KEY="")
QUESTIONS = mask_payload({"q": {"type": "noul", "instructions": "Tem risco?"}})

BOUNDARY_CALLS = {
    "chat_completion(user_prompt)": lambda: chat_completion("sys", RAW, OFFLINE),
    "call_jev(state)": lambda: call_jev({"clausula": RAW}, QUESTIONS, OFFLINE),
    "call_jev(questions)": lambda: call_jev(
        mask_payload({"clausula": "x"}), {"q": {"type": "noul", "instructions": RAW}}, OFFLINE
    ),
    "embed_text(text)": lambda: embed_text(RAW, OFFLINE),
    "start_analysis(masked_text)": lambda: start_analysis(
        None, None, filename_alias=resolve_doc_alias("x.txt"), masked_text=RAW, params={}
    ),
    "start_analysis(filename_alias)": lambda: start_analysis(
        None, None, filename_alias="minuta_Carlos_Eduardo_Mendes.txt", masked_text=mask_personal_data(RAW), params={}
    ),
}


@pytest.mark.parametrize("where", BOUNDARY_CALLS)
async def test_boundary_refuses_plain_str_before_any_trace(where, capture):
    with tracing_session(langsmith_client=capture.client, mlflow_uri=capture.mlflow_uri):
        with pytest.raises(UnmaskedTextError, match=re.escape(where)) as exc:
            await BOUNDARY_CALLS[where]()
    assert "src.ingest.masking.mask_personal_data" in str(exc.value)  # a mensagem nomeia a correcao
    sent = str(exc.value) + capture.blob.decode() + capture.mlflow_blob.decode()
    assert [s for s in (NAME, "Mendes", CPF, "99988877766") if s in sent] == []


async def test_boundary_accepts_the_same_text_once_masked():
    text, _ = await chat_completion("sys", mask_personal_data(RAW), OFFLINE)
    res = await call_jev(mask_payload({"clausula": RAW}), QUESTIONS, OFFLINE)
    emb = await embed_text(mask_personal_data(RAW), OFFLINE)
    assert text and "q" in res["answers"] and emb.vector
