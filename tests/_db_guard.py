"""Guarda contra rodar a suite (que apaga o schema `public`) no banco errado.

Fica fora do conftest para poder ser testada como funcao pura, sem Postgres.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import Settings

TEST_DB_SUFFIX = "_test"

# Caminho absoluto: os testes acham o .env da raiz do repo mesmo quando o
# pytest e chamado de outra pasta.
REPO_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class SuiteSettings(BaseSettings):
    """Bancos usados pela suite. Prioridade: variavel de ambiente > .env > padrao.

    ``DATABASE_URL`` e lido do mesmo arquivo que ``TEST_DATABASE_URL`` para que
    a guarda compare os dois valores vindos da mesma fonte.
    """

    TEST_DATABASE_URL: str = "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_test"
    DATABASE_URL: str = Settings.model_fields["DATABASE_URL"].default

    model_config = SettingsConfigDict(
        env_file=REPO_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class UnsafeTestDatabaseError(RuntimeError):
    """O banco de teste configurado nao pode ser apagado com seguranca."""


def database_name(dsn: str) -> str:
    """Nome do database de uma DSN ``postgresql://...`` (vazio se ausente)."""
    return unquote(urlsplit(dsn).path.lstrip("/"))


def assert_safe_test_database(test_dsn: str, dev_dsn: str) -> None:
    """Levanta :class:`UnsafeTestDatabaseError` se ``test_dsn`` nao for descartavel.

    Regras: o nome do banco de teste precisa terminar em ``_test`` e nao pode ser
    o mesmo banco do ``DATABASE_URL`` de desenvolvimento. A comparacao e pelo
    nome do database, de proposito mais estrita que comparar a DSN inteira:
    mudar so usuario, senha ou a grafia do host nao torna o alvo seguro.
    """
    test_name = database_name(test_dsn)
    if not test_name.endswith(TEST_DB_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL aponta para o banco {test_name!r}, que nao termina em "
            f"{TEST_DB_SUFFIX!r}. A suite apaga o schema public; abortando."
        )
    if test_name == database_name(dev_dsn):
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL e DATABASE_URL apontam para o mesmo banco {test_name!r}. "
            "A suite apaga o schema public; abortando."
        )
