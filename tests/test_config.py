"""A configuracao exige modelo pago para retencao zero e nao versiona senha."""

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_zero_retention_rejects_free_embedding_model():
    with pytest.raises(ValidationError):
        Settings(
            EMBEDDING_ZERO_RETENTION=True,
            EMBEDDING_MODEL="nvidia/x:free",
            _env_file=None,
        )


def test_zero_retention_accepts_paid_embedding_model():
    settings = Settings(
        EMBEDDING_ZERO_RETENTION=True,
        EMBEDDING_MODEL="openai/text-embedding-3-small",
        _env_file=None,
    )

    assert settings.EMBEDDING_MODEL == "openai/text-embedding-3-small"


def test_free_embedding_model_is_allowed_without_zero_retention():
    settings = Settings(
        EMBEDDING_ZERO_RETENTION=False,
        EMBEDDING_MODEL="nvidia/x:free",
        _env_file=None,
    )

    assert settings.EMBEDDING_MODEL == "nvidia/x:free"


def test_default_database_urls_have_no_password():
    for field in ("DATABASE_URL", "TEST_DATABASE_URL"):
        default = Settings.model_fields[field].default
        assert ":" not in default.removeprefix("postgresql://").split("@")[0]
