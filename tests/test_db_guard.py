"""Testes da guarda que impede apagar o banco de desenvolvimento."""

import pytest

from tests.conftest import assert_disposable_database


def test_accepts_database_name_ending_in_test():
    assert_disposable_database("postgresql://u:p@h:5433/leia_lab_test")


def test_rejects_development_database():
    with pytest.raises(RuntimeError):
        assert_disposable_database("postgresql://u:p@h:5433/leia_lab")


def test_rejects_database_name_with_suffix_after_test():
    with pytest.raises(RuntimeError):
        assert_disposable_database("postgresql://u:p@h:5433/leia_lab_test_copia")


def test_rejects_dsn_without_database_name():
    with pytest.raises(RuntimeError):
        assert_disposable_database("postgresql://u:p@h:5433")


def test_error_message_does_not_leak_password():
    with pytest.raises(RuntimeError) as exc_info:
        assert_disposable_database("postgresql://u:p4ss@h:5433/leia_lab")
    assert "p4ss" not in str(exc_info.value)
