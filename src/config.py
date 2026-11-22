from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: str = ""
    CHAT_MODEL: str = "openai/gpt-4o-mini"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    TYPESAFE_API_KEY: str = ""
    TYPESAFE_BASE_URL: str = "https://api.typesafe.ai/v1/systemone"
    JEV_MODEL: str = "jev-1.14.0"
    # Token de servico da API (src/api): bearer exigido em /v1/analyses. A API
    # recusa subir sem ele. Nao tem relacao com os logins do Django Admin.
    LEIA_API_TOKEN: str = ""
    # Rastreio da API: so o MLflow self-hosted (vazio = a API nao rastreia nada). A LangSmith
    # fica fora da API; o conteudo enviado e o mesmo do CLI --trace, sempre mascarado.
    MLFLOW_TRACKING_URI: str = ""
    MLFLOW_EXPERIMENT_NAME: str = "leia-lab"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
