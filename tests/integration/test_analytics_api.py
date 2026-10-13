"""Phase 2–10 endpoints against the loaded warehouse (skipped when it is not loaded)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_geo_regions_have_polygons_and_values(client: TestClient) -> None:
    body = client.get("/api/v1/geo/regions", params={"metric": "population_total"}).json()
    assert len(body["features"]) == 14
    assert all(f["geometry"]["type"] == "MultiPolygon" for f in body["features"])
    assert all(f["properties"]["value"] for f in body["features"])


def test_every_district_is_located(client: TestClient) -> None:
    body = client.get("/api/v1/geo/districts").json()
    assert len(body["features"]) == 208
    approx = [f for f in body["features"] if f["properties"]["geom_approx"]]
    assert all(f["geometry"]["type"] == "Point" for f in approx)


def test_recommend_contract(client: TestClient) -> None:
    r = client.post("/api/v1/recommend", json={"business_type": "pharmacy", "region": "1730", "limit": 5}).json()
    assert r["scope"] == {"level": "district", "region_soato": "1730", "candidates": 19, "ranked": 19}
    assert r["disclaimer"].startswith("Business Opportunity Score is an analytical model")
    top = r["results"][0]
    assert round(sum(b["contribution"] for b in top["breakdown"]), 2) == top["score"]
    assert all(b["sources"] for b in top["breakdown"])


def test_recommend_unknown_type_is_404(client: TestClient) -> None:
    r = client.post("/api/v1/recommend", json={"business_type": "spaceport"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_forecast_has_intervals(client: TestClient) -> None:
    f = client.get("/api/v1/forecast/population_total/region/1730").json()
    assert len(f["forecast"]) == 3
    for p in f["forecast"]:
        assert p["lo95"] <= p["lo80"] <= p["yhat"] <= p["hi80"] <= p["hi95"]
    assert "not an official statistic" in f["note"]


def test_compare_and_search(client: TestClient) -> None:
    c = client.get("/api/v1/compare", params={"indicator": "enterprises_active", "entities": "1730,1703"}).json()
    assert [r["soato"] for r in c["rows"]] == ["1730", "1703"]
    assert all(r["per_1000_people"] for r in c["rows"])
    s = client.get("/api/v1/territories/search", params={"q": "Qo‘qon"}).json()
    assert s[0]["name"] == "Kokand city"


def test_validation_errors_use_the_error_model(client: TestClient) -> None:
    r = client.get("/api/v1/statistics", params={"indicator": "population_total", "year": "abc"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_monitoring_and_feedback(client: TestClient) -> None:
    for part in ("data", "models", "recommendations", "agent"):
        assert client.get(f"/api/v1/monitoring/{part}").status_code == 200
    assert client.post("/api/v1/feedback", json={"rating": 1, "target": "chat"}).json()["status"] == "saved"
    assert client.post("/api/v1/feedback", json={"rating": 5}).status_code == 422


def test_metrics_exports_batch_gauges(client: TestClient) -> None:
    text = client.get("/metrics").text
    for name in ("data_quality_check_passed", "feature_drift_psi", "model_backtest_smape", "user_feedback_total"):
        assert name in text
