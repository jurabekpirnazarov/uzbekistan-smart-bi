"""One test per MCP tool (PLAN.md Phase 7), called in-process through FastMCP."""

from __future__ import annotations

import asyncio
import json

import pytest

from mcp_server.server import mcp
from tests.conftest import requires_db

pytestmark = requires_db

CASES = {
    "ping": {},
    "search_statistics": {"query": "population"},
    "get_indicator": {"code": "enterprises_active"},
    "get_region_statistics": {"region": "Farg‘ona", "indicators": ["population_total"]},
    "get_district_statistics": {"region": "Fergana", "indicators": ["enterprises_active"]},
    "get_time_series": {"indicator": "population_total", "level": "region", "entity": "1730"},
    "compare_regions": {"entities": ["Andijan", "Namangan"], "indicators": ["population_total"]},
    "get_population_data": {"level": "district", "entity": "Kokand"},
    "get_income_data": {},
    "get_business_activity": {"level": "region", "entity": "Samarkand"},
    "get_retail_data": {"level": "country"},
    "forecast_indicator": {"indicator": "population_total", "level": "region", "entity": "Samarkand"},
    "calculate_business_score": {"business_type": "bakery", "region": "Fergana", "limit": 3},
    "list_business_types": {},
    "retrieve_documents": {"query": "permanent population definition"},
    "get_growth_ranking": {"indicator": "enterprises_active", "level": "region", "year_from": 2020, "limit": 3},
}


def call(name: str, args: dict) -> dict:
    res = asyncio.run(mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_every_tool_has_a_case() -> None:
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == set(CASES)


@pytest.mark.parametrize("tool", sorted(CASES))
def test_tool_returns_contract(tool: str) -> None:
    out = call(tool, CASES[tool])
    assert "error" not in out, out
    assert {"data", "meta", "warnings"} <= set(out)


def test_income_is_reported_as_missing() -> None:
    out = call("get_income_data", {"level": "district"})
    assert out["data"] is None and "no official district-level income" in out["warnings"][0]


def test_errors_are_structured() -> None:
    out = call("get_time_series", {"indicator": "nope", "level": "region", "entity": "1730"})
    assert out["error"]["code"] == "not_found"
