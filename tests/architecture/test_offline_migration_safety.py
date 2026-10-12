from unittest.mock import Mock

import pytest

from scripts import db_offline_evidence_migration_smoke as smoke


@pytest.fixture
def isolated_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DIMAX_OFFLINE_EVIDENCE_MIGRATION", "1")
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg2://postgres:qa-only@db:5432/{smoke.DATABASE}")


@pytest.mark.parametrize("name,value", [
    ("APP_ENV", "production"), ("APP_ENV", "development"),
    ("DIMAX_OFFLINE_EVIDENCE_MIGRATION", "0"),
    ("DATABASE_URL", ""), ("DATABASE_URL", "not-a-database-url"),
    ("DATABASE_URL", "postgresql+psycopg2://postgres:qa-only@db:5432/dimax_acceptance_tests"),
    ("DATABASE_URL", f"postgresql+psycopg2://postgres:qa-only@production:5432/{smoke.DATABASE}"),
    ("DATABASE_URL", f"postgresql+psycopg2://postgres:qa-only@db:5433/{smoke.DATABASE}"),
    ("DATABASE_URL", f"postgresql+psycopg://postgres:qa-only@db:5432/{smoke.DATABASE}"),
    ("DATABASE_URL", f"postgresql+psycopg2://postgres:qa-only@db:5432/{smoke.DATABASE}?host=production"),
])
def test_unsafe_configuration_fails_before_connecting(isolated_environment, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    connect = Mock(side_effect=AssertionError("Must not connect"))
    migrate = Mock(side_effect=AssertionError("Must not migrate"))
    monkeypatch.setattr(smoke, "create_engine", connect)
    monkeypatch.setattr(smoke.command, "upgrade", migrate)
    with pytest.raises(RuntimeError) as error:
        smoke.main()
    assert "qa-only" not in str(error.value)
    connect.assert_not_called()
    migrate.assert_not_called()


def test_exact_isolated_url_is_accepted(isolated_environment):
    assert smoke._validated_database_url().database == smoke.DATABASE


@pytest.mark.parametrize("database,occupied", [("dimax", False), (smoke.DATABASE, True)])
def test_wrong_or_populated_database_is_refused(database, occupied):
    connection = Mock()
    connection.execute.side_effect = [Mock(scalar_one=lambda: database), Mock(scalar_one=lambda: occupied)]
    with pytest.raises(RuntimeError):
        smoke._require_empty_database(connection)


def test_empty_disposable_database_is_accepted():
    connection = Mock()
    connection.execute.side_effect = [Mock(scalar_one=lambda: smoke.DATABASE), Mock(scalar_one=lambda: False)]
    smoke._require_empty_database(connection)
