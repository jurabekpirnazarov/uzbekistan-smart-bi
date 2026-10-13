"""Runs against the real warehouse (local Postgres loaded by `python manage.py ingest`).

Skipped automatically when the database is not reachable or not loaded.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_engine
from app.main import create_app


def _db_loaded() -> bool:  # kept local: this module only needs observations
    try:
        with get_engine().connect() as c:
            return (c.execute(text("SELECT count(*) FROM observations")).scalar() or 0) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_loaded(), reason="warehouse not running / not loaded")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_overview_has_population_kpi(client: TestClient) -> None:
    body = client.get("/api/v1/overview").json()
    pop = next(k for k in body["kpis"] if k["indicator"] == "population_total")
    assert pop["unit"] == "persons" and pop["value"] > 30_000_000
    assert body["regions"] == 14


def test_region_ranking_sums_to_country(client: TestClient) -> None:
    r = client.get("/api/v1/statistics", params={"indicator": "population_total", "level": "region"}).json()
    assert len(r["items"]) == 14
    country = client.get("/api/v1/timeseries/population_total/country/1700").json()
    country_value = next(p["value"] for p in country["points"] if p["year"] == r["year"])
    assert abs(r["total"] - country_value) / country_value < 0.02
    assert r["meta"]["sources"][0]["siat_dataset_id"] == 246
    assert r["meta"]["is_synthetic"] is False


def test_district_sum_matches_region_total(client: TestClient) -> None:
    d = client.get(
        "/api/v1/statistics", params={"indicator": "population_total", "level": "district", "region": "1730"}
    ).json()
    reg = client.get("/api/v1/timeseries/population_total/region/1730").json()
    reg_value = next(p["value"] for p in reg["points"] if p["year"] == d["year"])
    assert abs(d["total"] - reg_value) / reg_value < 0.02


def test_growth_rates_have_no_total(client: TestClient) -> None:
    r = client.get("/api/v1/statistics", params={"indicator": "trade_services_growth"}).json()
    assert r["total"] is None
    assert all(i["share"] is None for i in r["items"])


def test_unknown_indicator_is_404(client: TestClient) -> None:
    r = client.get("/api/v1/statistics", params={"indicator": "nope"})
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_region_only_indicator_has_no_district_level(client: TestClient) -> None:
    ind = next(i for i in client.get("/api/v1/indicators").json() if i["code"] == "small_business_share_gva")
    assert "district" not in ind["levels"]
