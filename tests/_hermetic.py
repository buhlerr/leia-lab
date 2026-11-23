"""Ambiente que as duas suites (pytest e testes do admin) impoem antes de qualquer teste.

Ninguem herda credencial, URI de servico real nem rastreio de quem roda a suite
(ex.: ``shelve run -- pytest``): d3a369a mandou traces ao MLflow real, e a suite
fazia chamadas ao Jev e uploads a LangSmith com texto de contrato.
Um teste que precisa de um valor o define com ``monkeypatch.setenv`` ou no ``Settings`` que monta.
"""

from __future__ import annotations

import os

from src.config import Settings

_BLANK_SUFFIXES = ("_KEY", "_TOKEN", "_URI", "_SECRET")
_TRACING_OFF = {
    "LANGSMITH_API_KEY": "",
    "LANGCHAIN_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_TRACING_V2": "false",
    "LANGCHAIN_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}
_ADMIN_SERVICES = {"LEIA_API_URL": "http://leia-api:8080", "LEIA_MLFLOW_URL": ""}


def hermetic_environment() -> dict[str, str]:
    """Derivado de ``Settings``: campo novo terminado em _KEY/_TOKEN/_URI/_SECRET fica vazio e
    campo *_URL (fora DATABASE_URL) volta ao padrao, sem cair num valor do ``.env``."""
    env: dict[str, str] = {}
    for name, field in Settings.model_fields.items():
        if name.endswith(_BLANK_SUFFIXES):
            env[name] = ""
        elif name.endswith("_URL") and name != "DATABASE_URL":
            env[name] = str(field.default)
    return {**env, **_TRACING_OFF, **_ADMIN_SERVICES}


def apply() -> None:
    os.environ.update(hermetic_environment())
