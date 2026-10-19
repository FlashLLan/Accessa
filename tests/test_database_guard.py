"""The test suite can only reach the database named by TEST_DATABASE_URL."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from conftest import DEV_DATABASE_URL, TEST_DATABASE_URL, ForbiddenDatabaseConnection
from database.db import engine as application_engine


def test_application_engine_points_at_test_database():
    assert application_engine.url.database == make_url(TEST_DATABASE_URL).database
    with application_engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == make_url(TEST_DATABASE_URL).database


@pytest.mark.skipif(not DEV_DATABASE_URL, reason="no development DATABASE_URL configured")
def test_suite_cannot_connect_to_development_database():
    dev_engine = create_engine(DEV_DATABASE_URL)
    with pytest.raises(ForbiddenDatabaseConnection):
        dev_engine.connect()
    dev_engine.dispose()


@pytest.mark.parametrize("change", [
    {"database": "postgres"},
    {"database": "some_other_test"},
    {"port": 5433},
    {"host": "127.0.0.2"},
])
def test_suite_cannot_connect_anywhere_but_test_database(change):
    engine = create_engine(make_url(TEST_DATABASE_URL).set(**change))
    with pytest.raises(ForbiddenDatabaseConnection):
        engine.connect()
    engine.dispose()
