"""As duas suites nao alcancam servico pago nem rastreio real pelo ambiente de quem as roda."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langsmith.utils import tracing_is_enabled

from src.config import Settings

REPO = Path(__file__).resolve().parents[1]

# O ambiente de quem roda a suite sob `shelve run`, com os servicos apontando para lugar nenhum.
# Caixa diferente de proposito: o Linux aceita as duas e o pydantic le o env sem caixa.
_POISON = {
    "OPENROUTER_API_KEY": "or_real",
    "openrouter_api_key": "or_real_lower",
    "TYPESAFE_API_KEY": "ts_real",
    "typesafe_api_key": "ts_real_lower",
    "LEIA_API_TOKEN": "tok_real",
    "MLFLOW_TRACKING_URI": "http://127.0.0.1:9",
    "OPENROUTER_BASE_URL": "http://127.0.0.1:9/or",
    "TYPESAFE_BASE_URL": "http://127.0.0.1:9/ts",
    "LANGSMITH_API_KEY": "lsv2_real",
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_TRACING_V2": "true",
    "LANGCHAIN_TRACING_V2": "true",
    "LEIA_MLFLOW_URL": "http://127.0.0.1:9",
    "LEIA_API_URL": "http://127.0.0.1:9",
}


def test_settings_carry_no_external_credential_or_service():
    loaded = Settings()
    for name, field in Settings.model_fields.items():
        if name.endswith(("_KEY", "_TOKEN", "_URI", "_SECRET")):
            assert not getattr(loaded, name), f"{name} vazou para a suite"
        elif name.endswith("_URL") and name != "DATABASE_URL":
            assert getattr(loaded, name) == field.default, f"{name} vazou para a suite"


def test_langsmith_tracing_is_off():
    assert not tracing_is_enabled()


def test_case_variant_of_a_credential_is_blanked(monkeypatch):
    """openrouter_api_key minusculo (o Linux aceita) nao sobrevive ao bootstrap:
    o pydantic le o env sem caixa, entao a variante vale tanto quanto a oficial."""
    from tests._hermetic import apply

    monkeypatch.setenv("openrouter_api_key", "or_real_lower")
    monkeypatch.setenv("typesafe_api_key", "ts_real_lower")
    apply()
    assert os.environ["openrouter_api_key"] == ""
    assert os.environ["typesafe_api_key"] == ""


def _run_poisoned(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_POISON}
    return subprocess.run([sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)


def test_pytest_suite_is_hermetic_under_a_real_environment():
    done = _run_poisoned("-m", "pytest", "-q", "-p", "no:cacheprovider", __file__, "-k", "not real_environment")
    assert done.returncode == 0, done.stdout[-2000:]


def test_admin_suite_is_hermetic_under_a_real_environment():
    done = _run_poisoned("-m", "src.management.manage", "test", "src.management.domain.tests.HermeticTests")
    assert done.returncode == 0, done.stderr[-2000:]
