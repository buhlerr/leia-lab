from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # A senha vem da .env; nunca versionar valor real.
    DATABASE_URL: str = "postgresql://leia@localhost:5433/leia_lab"
    # Banco descartavel da suite: o conftest recria o schema `public` a cada teste.
    # A senha vem da .env; nunca versionar valor real.
    TEST_DATABASE_URL: str = "postgresql://leia@localhost:5433/leia_lab_test"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: str = ""
    # "deepseek": API direta, com cache de prefixo, sem opcao de retencao zero.
    # "openrouter": aceita a restricao de retencao zero; use para minutas reais.
    CHAT_PROVIDER: Literal["deepseek", "openrouter"] = "deepseek"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_API_KEY: str = ""
    CHAT_MODEL: str = "deepseek-flash"
    EMBEDDING_MODEL: str = "nvidia/nemotron-3.5-embed-8b:free"
    # Nenhum embedding gratuito tem endpoint sem retencao, e a busca pode levar
    # trechos da minuta. Antes de usar minutas reais: ligar isto e usar um modelo
    # com endpoint sem retencao, como openai/text-embedding-3-small.
    EMBEDDING_ZERO_RETENTION: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_paid_embedding_for_zero_retention(self) -> "Settings":
        # Modelos gratuitos nao tem endpoint sem retencao.
        if self.EMBEDDING_ZERO_RETENTION and self.EMBEDDING_MODEL.endswith(":free"):
            raise ValueError(
                "EMBEDDING_ZERO_RETENTION exige um modelo com endpoint sem retencao; "
                "modelos gratuitos nao tem essa opcao. Use um modelo pago, como "
                "openai/text-embedding-3-small."
            )
        return self

    @property
    def chat_api_key(self) -> str:
        """Chave do provedor de chat ativo; vazia significa modo offline."""
        return self.DEEPSEEK_API_KEY if self.CHAT_PROVIDER == "deepseek" else self.OPENROUTER_API_KEY


# Restringe o roteamento do OpenRouter a endpoints sem retencao; minutas sao confidenciais.
ZERO_RETENTION_PROVIDER = {"zdr": True, "data_collection": "deny"}
