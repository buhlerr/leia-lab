"""A suite se recusa a apagar um banco que nao seja descartavel."""

from __future__ import annotations

import pytest

from tests._db_guard import UnsafeTestDatabaseError, assert_safe_test_database
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
