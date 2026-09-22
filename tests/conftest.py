import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import Flag, UserOverride, make_engine
from app.main import create_app


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    # Apply real migrations. Never drop or truncate a supplied database.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return url


@pytest.fixture
def flag_name(database_url):
    name = "test-" + uuid4().hex
    yield name
    engine = make_engine(database_url)
    with engine.begin() as connection:
        connection.execute(delete(UserOverride).where(UserOverride.flag_name == name))
        connection.execute(delete(Flag).where(Flag.name == name))
    engine.dispose()


@pytest.fixture
def app(database_url):
    return create_app(Settings(database_url=database_url))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client
