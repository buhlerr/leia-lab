from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_API_KEY: str = ""
    CHAT_MODEL: str = "deepseek/deepseek-v4.1-flash"
    CHAT_MAX_TOKENS: int = Field(default=1500, gt=0)
    CHAT_REASONING: Literal["off", "default", "minimal", "low", "medium", "high"] = "off"
    ANALYSIS_MAX_COST_USD: float = Field(default=0.05, ge=0, allow_inf_nan=False)
    # Pede aos provedores do OpenRouter que nao retenham os dados enviados.
    OPENROUTER_DATA_COLLECTION: Literal["allow", "deny"] = "deny"
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    TYPESAFE_API_KEY: str = ""
    TYPESAFE_BASE_URL: str = "https://api.typesafe.ai/v1/systemone"
    JEV_MODEL: str = "jev-1.14.0"
    LEIA_API_TOKEN: str = ""
    MLFLOW_TRACKING_URI: str = ""
    MLFLOW_EXPERIMENT_NAME: str = "leia-lab"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
