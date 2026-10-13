from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import health as health_service


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_ok_when_db_reachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_service, "check_database", lambda: True)
    for path in ("/health", "/api/v1/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["db"] == "ok"


def test_health_503_when_db_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_service, "check_database", lambda: False)
    r = client.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "down", "version": r.json()["version"]}


def test_request_id_is_echoed_or_generated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_service, "check_database", lambda: True)
    assert client.get("/health", headers={"X-Request-ID": "abc123"}).headers["X-Request-ID"] == "abc123"
    assert len(client.get("/health").headers["X-Request-ID"]) == 32


def test_metrics_endpoint_exposes_http_metrics(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_service, "check_database", lambda: True)
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text
