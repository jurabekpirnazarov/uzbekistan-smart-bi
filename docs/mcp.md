# MCP server

`mcp_server/server.py` exposes the platform's statistics as Model Context Protocol tools (official `mcp`
Python SDK, FastMCP). Tools call `backend/app/services` directly — no duplicated logic.

- **streamable-http:** `python -m mcp_server.server` → `http://localhost:8100/mcp` (started by `manage.py dev`)
- **stdio:** `python -m mcp_server.server --transport stdio`
- Health: `GET http://localhost:8100/health` · metrics: `GET http://localhost:8100/metrics`
  (`mcp_tool_calls_total{tool,status}`, `mcp_tool_latency_seconds{tool}`)

Every tool returns `{"data": …, "meta": {"sources": […], "is_synthetic": bool, "period": …}, "warnings": […]}`.
Errors are returned, not raised: `{"error": {"code": "not_found" | "bad_arguments" | "internal", "message": …}}`.
Places can be given as SOATO codes or names in English, Uzbek or Russian (`"Farg‘ona"`, `"Ферганская"`).

| Tool | Arguments | Returns |
|---|---|---|
| `ping` | — | server + database status |
| `search_statistics` | `query`, `category?` | matching indicators |
| `get_indicator` | `code` | unit, levels, years, SIAT dataset id |
| `get_region_statistics` | `region`, `indicators[]`, `year?` | values for one region |
| `get_district_statistics` | `region`, `indicators[]`, `district?`, `year?` | one district, or all districts of the region |
| `get_time_series` | `indicator`, `level`, `entity`, `year_from?`, `year_to?` | yearly history |
| `compare_regions` | `entities[]`, `indicators[]`, `year?` | side-by-side values + per 1,000 people |
| `get_population_data` | `level`, `entity?`, `year?` | total / urban / rural population |
| `get_income_data` | `level`, `entity?`, `year?` | **warning: no official district income data** |
| `get_business_activity` | `level`, `entity?`, `year?` | operating / registered / new businesses |
| `get_retail_data` | `level`, `entity?`, `year?` | trade services (retail proxy) + warning |
| `forecast_indicator` | `indicator`, `level`, `entity`, `horizon` | forecast + 80/95 % intervals (model prediction) |
| `calculate_business_score` | `business_type`, `region?`, `target?`, `weights_override?`, `budget_uzs?` | scores with breakdown |
| `list_business_types` | — | the YAML profiles |
| `retrieve_documents` | `query`, `k` | methodology snippets with citations |
| `get_growth_ranking` | `indicator`, `level`, `year_from`, `year_to?`, `region?` | all territories ranked by growth |

Sample output (`get_population_data`, `level=region`, `entity="Farg‘ona"`):

```json
{
  "data": {"population_total": {"territory": "Fergana region", "soato": "1730", "level": "region", "year": 2026, "value": 4223000.0}},
  "meta": {"sources": [{"name": "siat", "url": "https://siat.stat.uz/media/uploads/sdmx/sdmx_data_246.json", "siat_dataset_id": 246}], "is_synthetic": false, "period": null},
  "warnings": []
}
```

## Connect

**MCP Inspector:** `npx @modelcontextprotocol/inspector` → transport *Streamable HTTP* → URL
`http://localhost:8100/mcp`.

**Claude Desktop** (`claude_desktop_config.json`, stdio):

```json
{
  "mcpServers": {
    "uz-smart-bi": {
      "command": "C:\\path\\to\\ITPU_BI\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server", "--transport", "stdio"],
      "cwd": "C:\\path\\to\\ITPU_BI"
    }
  }
}
```

The database must be running (`python manage.py db-start`). Tests: `tests/integration/test_mcp_tools.py`
(one test per tool).
