from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab"
    # Banco descartavel da suite: o conftest recria o schema `public` a cada teste.
    TEST_DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_test"
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

    @property
    def chat_api_key(self) -> str:
        """Chave do provedor de chat ativo; vazia significa modo offline."""
        return self.DEEPSEEK_API_KEY if self.CHAT_PROVIDER == "deepseek" else self.OPENROUTER_API_KEY


# Restringe o roteamento do OpenRouter a endpoints sem retencao; minutas sao confidenciais.
ZERO_RETENTION_PROVIDER = {"zdr": True, "data_collection": "deny"}
