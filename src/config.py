from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab"
    # Banco descartavel da suite: o conftest recria o schema `public` a cada teste.
    TEST_DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_test"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: str = ""
    CHAT_MODEL: str = "openai/gpt-4o-mini"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
