"""A suite nao alcanca servico pago nem rastreio real pelo ambiente de quem a roda."""

from __future__ import annotations

from langsmith.utils import tracing_is_enabled

from src.config import Settings


def test_settings_carry_no_external_credential():
    loaded = Settings()
    leaked = {
        name: "<set>"
        for name in Settings.model_fields
        if name.endswith(("_KEY", "_TOKEN", "_URI")) and getattr(loaded, name)
    }
    assert not leaked, f"credencial externa vazou para a suite: {leaked}"


def test_langsmith_tracing_is_off():
    assert not tracing_is_enabled()
