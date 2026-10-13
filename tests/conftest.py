import pytest

from ehr_rwe_eln.config import DatabaseSettings

# Tests use their own database in the Compose Postgres, never the one the build scripts fill.
TEST_DB = "ehr_rwe_eln_test"


@pytest.fixture(scope="session")
def database():
    settings = DatabaseSettings()
    with settings.connect(autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", [TEST_DB])
        if not exists.fetchone():
            admin.execute(f"CREATE DATABASE {TEST_DB}")
    return settings


def rolled_back(settings):
    """A connection whose work, schema changes included, is rolled back when the test ends."""
    con = settings.connect(dbname=TEST_DB)
    try:
        yield con
    finally:
        con.rollback()
        con.close()


@pytest.fixture
def pg(database):
    yield from rolled_back(database)


@pytest.fixture(scope="module")
def pg_module(database):
    yield from rolled_back(database)
