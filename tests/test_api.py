from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.config import Settings
from app.db import UserOverride
from app.main import create_app

pytestmark = pytest.mark.integration


def create(client, name, enabled=False):
    return client.post(
        "/flags", json={"name": name, "description": "Checkout", "default_enabled": enabled}
    )


def evaluate(client, name, user="alice"):
    return client.get(f"/flags/{name}/evaluate", params={"user_id": user})


def test_create_duplicate_and_restart(client, flag_name, database_url):
    response = create(client, flag_name)
    assert response.status_code == 201
    assert response.headers["location"] == f"/flags/{flag_name}"
    assert response.json()["description"] == "Checkout"
    assert create(client, flag_name).status_code == 409
    client.put(f"/flags/{flag_name}/users/alice", json={"enabled": True})
    # A fresh app has a fresh cache and engine; data must come from PostgreSQL.
    with TestClient(create_app(Settings(database_url=database_url))) as restarted:
        assert restarted.get(f"/flags/{flag_name}").json()["default_enabled"] is False
        assert evaluate(restarted, flag_name).json()["enabled"] is True


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_default_and_override_precedence(client, flag_name, default, override):
    create(client, flag_name, default)
    assert evaluate(client, flag_name).json()["enabled"] is default
    for _ in range(2):
        response = client.put(f"/flags/{flag_name}/users/alice", json={"enabled": override})
        assert response.status_code == 200
    assert evaluate(client, flag_name).json() == {
        "flag_name": flag_name,
        "user_id": "alice",
        "enabled": override,
        "source": "override",
    }
    assert evaluate(client, flag_name, "bob").json()["enabled"] is default
    for _ in range(2):
        response = client.put(f"/flags/{flag_name}/default", json={"default_enabled": not default})
        assert response.status_code == 200
    assert evaluate(client, flag_name, "bob").json()["enabled"] is not default
    assert evaluate(client, flag_name).json()["enabled"] is override


def test_cache_hit_skips_sql_and_override_update_invalidates(client, app, flag_name):
    create(client, flag_name)
    queries = []

    def record(*args):
        queries.append(args[2])

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        assert evaluate(client, flag_name).json()["enabled"] is False
        first_count = len(queries)
        assert first_count == 1
        assert evaluate(client, flag_name).json()["enabled"] is False
        assert len(queries) == first_count
        client.put(f"/flags/{flag_name}/users/alice", json={"enabled": True})
        assert evaluate(client, flag_name).json()["enabled"] is True
        client.put(f"/flags/{flag_name}/users/alice", json={"enabled": False})
        assert evaluate(client, flag_name).json()["enabled"] is False
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)


def test_unknown_flag(client, flag_name):
    assert evaluate(client, flag_name).status_code == 404
    assert client.get(f"/flags/{flag_name}").status_code == 404
    assert (
        client.put(f"/flags/{flag_name}/default", json={"default_enabled": True}).status_code == 404
    )
    assert client.put(f"/flags/{flag_name}/users/alice", json={"enabled": True}).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": "bad name"},
        {"name": "x" * 101},
        {"default_enabled": "false"},
        {"default_enabled": 1},
        {"default_enabled": None},
        {"description": "x" * 1001},
        {"description": "bad\x00value"},
        {"unexpected": True},
    ],
)
def test_invalid_creation(client, flag_name, changes):
    body = {"name": flag_name, "default_enabled": False}
    body.update(changes)
    assert client.post("/flags", json=body).status_code == 422
    assert client.get(f"/flags/{flag_name}").status_code == 404


def test_invalid_evaluation_and_update(client, flag_name):
    create(client, flag_name)
    assert client.get(f"/flags/{flag_name}/evaluate").status_code == 422
    assert evaluate(client, flag_name, "").status_code == 422
    assert evaluate(client, flag_name, "x" * 129).status_code == 422
    assert client.put(f"/flags/{flag_name}/default", json={}).status_code == 422
    assert (
        client.put(f"/flags/{flag_name}/users/alice", json={"enabled": "false"}).status_code == 422
    )


def test_db_failure_returns_503_but_live_and_cached_reads_work(client, app, flag_name):
    create(client, flag_name)
    evaluate(client, flag_name)

    def fail(*args):
        raise OperationalError("query", {}, Exception("sensitive connection detail"))

    event.listen(app.state.engine, "before_cursor_execute", fail)
    try:
        assert client.get("/health/live").status_code == 200
        assert evaluate(client, flag_name).status_code == 200
        for response in [
            evaluate(client, flag_name, "uncached"),
            client.get("/health/ready"),
            client.put(f"/flags/{flag_name}/default", json={"default_enabled": True}),
        ]:
            assert response.status_code == 503
            assert response.json() == {"detail": "Database temporarily unavailable"}
    finally:
        event.remove(app.state.engine, "before_cursor_execute", fail)
    app.state.cache.invalidate()
    assert evaluate(client, flag_name).json()["enabled"] is False


def test_concurrent_override_upserts_leave_one_row(client, app, flag_name):
    create(client, flag_name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(
                lambda _: client.put(f"/flags/{flag_name}/users/alice", json={"enabled": True}),
                range(8),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    with app.state.engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(UserOverride)
                .where(UserOverride.flag_name == flag_name)
            )
            == 1
        )
    assert evaluate(client, flag_name).json()["enabled"] is True


def test_read_overlapping_write_cannot_repopulate_stale_cache(client, app, flag_name):
    create(client, flag_name)
    reached_fill, release_fill = Event(), Event()
    original_put = app.state.cache.put

    def delayed_put(key, value, generation):
        reached_fill.set()
        assert release_fill.wait(timeout=10)
        original_put(key, value, generation)

    app.state.cache.put = delayed_put
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_read = pool.submit(evaluate, client, flag_name)
            try:
                assert reached_fill.wait(timeout=10)
                assert (
                    client.put(
                        f"/flags/{flag_name}/default", json={"default_enabled": True}
                    ).status_code
                    == 200
                )
            finally:
                release_fill.set()
            # An overlapping read may see the previous committed state.
            assert pending_read.result().json()["enabled"] is False
    finally:
        app.state.cache.put = original_put
    # A request started after the write response must see the new state.
    assert evaluate(client, flag_name).json()["enabled"] is True


def test_health(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_readiness_reports_missing_schema(client, app):
    def fail(*args):
        raise ProgrammingError("query", {}, Exception("missing table"))

    event.listen(app.state.engine, "before_cursor_execute", fail)
    try:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200
    finally:
        event.remove(app.state.engine, "before_cursor_execute", fail)
