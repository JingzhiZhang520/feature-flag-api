import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db import make_engine
from app.main import create_app

TEST_KEY = "test-only-api-key-not-a-secret-123456789"


def test_deployment_requires_key():
    with pytest.raises(ValidationError, match="API_KEY is required"):
        Settings(_env_file=None, database_url="postgresql://unused", require_api_key=True)


def test_short_key_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://unused", api_key="short")


@pytest.mark.parametrize("prefix", ["postgres", "postgresql", "postgresql+psycopg"])
def test_cloud_database_url_preserves_tls_settings(prefix):
    engine = make_engine(f"{prefix}://user:password@localhost/db?sslmode=require")
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.query["sslmode"] == "require"
    engine.dispose()


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "incorrect"}])
def test_all_flag_routes_require_key_before_accessing_database(headers):
    app = create_app(
        Settings(
            _env_file=None,
            database_url="postgresql://unused",
            api_key=TEST_KEY,
            require_api_key=True,
        )
    )
    with TestClient(app) as client:
        requests = [
            ("POST", "/flags", {"name": "test", "default_enabled": False}),
            ("GET", "/flags/test", None),
            ("PUT", "/flags/test/default", {"default_enabled": True}),
            ("PUT", "/flags/test/users/alice", {"enabled": True}),
            ("GET", "/flags/test/evaluate?user_id=alice", None),
        ]
        for method, path, body in requests:
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401
            assert response.json() == {"detail": "Missing or invalid API key"}
        assert client.get("/health/live").status_code == 200
        assert client.get("/docs").status_code == 200


@pytest.mark.integration
def test_authorized_requests_and_cached_results_stay_protected(database_url, flag_name):
    app = create_app(Settings(database_url=database_url, api_key=TEST_KEY, require_api_key=True))
    with TestClient(app) as client:
        headers = {"X-API-Key": TEST_KEY}
        assert (
            client.post(
                "/flags", json={"name": flag_name, "default_enabled": False}, headers=headers
            ).status_code
            == 201
        )
        path = f"/flags/{flag_name}/evaluate?user_id=alice"
        assert client.get(path, headers=headers).json()["enabled"] is False
        assert client.get(path).status_code == 401
        assert (
            client.put(
                f"/flags/{flag_name}/users/alice", json={"enabled": True}, headers=headers
            ).status_code
            == 200
        )
        assert client.get(path, headers=headers).json()["enabled"] is True
