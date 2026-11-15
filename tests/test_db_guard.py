"""A suite se recusa a apagar um banco que nao seja descartavel."""

from __future__ import annotations

import pytest

from tests._db_guard import (
    REPO_ENV_FILE,
    SuiteSettings,
    UnsafeTestDatabaseError,
    assert_safe_test_database,
)
from tests.conftest import require_safe_test_database

DEV = "postgresql://leia:senha@localhost:5433/leia_lab"
TEST = "postgresql://leia:senha@localhost:5433/leia_lab_test"


def test_accepts_separate_database_ending_in_test():
    assert_safe_test_database(TEST, DEV)


@pytest.mark.parametrize(
    "test_dsn",
    [
        "postgresql://leia:senha@localhost:5433/leia_lab",  # o proprio banco de dev
        "postgresql://leia:senha@localhost:5433/leia_test_backup",  # _test no meio
        "postgresql://leia:senha@localhost:5433/",  # sem nome: asyncpg usaria o do usuario
        "postgresql://leia:senha@localhost:5433",
    ],
)
def test_rejects_database_not_ending_in_test(test_dsn):
    with pytest.raises(UnsafeTestDatabaseError, match="nao termina em"):
        assert_safe_test_database(test_dsn, DEV)


def test_rejects_test_database_equal_to_dev_database():
    with pytest.raises(UnsafeTestDatabaseError, match="mesmo banco"):
        assert_safe_test_database(TEST, TEST)


def test_rejects_same_database_reached_with_other_credentials_or_host():
    dev_same_db = "postgresql://outro:x@127.0.0.1:5433/leia_lab_test?sslmode=disable"
    with pytest.raises(UnsafeTestDatabaseError, match="mesmo banco"):
        assert_safe_test_database(TEST, dev_same_db)


def test_conftest_guard_aborts_the_whole_session():
    # pytest.exit levanta pytest.exit.Exception: a sessao para antes do DROP SCHEMA.
    with pytest.raises(pytest.exit.Exception) as excinfo:
        require_safe_test_database(test_dsn=DEV, dev_dsn=DEV)
    assert excinfo.value.returncode == pytest.ExitCode.USAGE_ERROR


def test_conftest_guard_allows_safe_target():
    require_safe_test_database(test_dsn=TEST, dev_dsn=DEV)


# --- De onde vem o TEST_DATABASE_URL -------------------------------------------


@pytest.fixture
def no_db_env(monkeypatch):
    """Garante que variaveis do shell nao mascarem o que o .env diz."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_reads_test_database_url_from_env_file(tmp_path, no_db_env):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TEST_DATABASE_URL=postgresql://u:p@db:5432/do_arquivo_test\n"
        "DATABASE_URL=postgresql://u:p@db:5432/do_arquivo\n",
        encoding="utf-8",
    )
    suite = SuiteSettings(_env_file=env_file)
    assert suite.TEST_DATABASE_URL.endswith("/do_arquivo_test")
    assert suite.DATABASE_URL.endswith("/do_arquivo")


def test_environment_variable_wins_over_env_file(tmp_path, no_db_env, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DATABASE_URL=postgresql://u:p@db/do_arquivo_test\n", encoding="utf-8")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://u:p@db/do_shell_test")
    assert SuiteSettings(_env_file=env_file).TEST_DATABASE_URL.endswith("/do_shell_test")


def test_defaults_point_to_a_safe_test_database(tmp_path, no_db_env):
    suite = SuiteSettings(_env_file=tmp_path / "nao_existe.env")
    assert suite.TEST_DATABASE_URL.endswith("/leia_lab_test")
    assert_safe_test_database(suite.TEST_DATABASE_URL, suite.DATABASE_URL)


def test_env_file_is_the_one_at_the_repo_root():
    assert REPO_ENV_FILE.name == ".env"
    assert (REPO_ENV_FILE.parent / "pyproject.toml").is_file()


def test_suite_settings_reads_the_repo_env_file_by_default():
    # Os testes acima passam `_env_file=` e por isso nao pegariam uma
    # SuiteSettings que deixasse de ler o .env: este verifica a ligacao padrao.
    assert SuiteSettings.model_config["env_file"] == REPO_ENV_FILE
