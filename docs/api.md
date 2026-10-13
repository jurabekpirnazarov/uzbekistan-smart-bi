# API

_Generated from the OpenAPI schema by `python -m app.api.docs_gen`. Interactive docs: http://localhost:8000/docs_

All routes are under `/api/v1`. Statistical responses carry `meta {sources[], period, unit, is_synthetic, retrieved_at}`. Errors use one model: `{code, message, details}` (404 `not_found`, 422 `validation_error`, 429 `rate_limited`). `/chat` is rate limited to 20 requests per minute per IP.

| Method | Path | Summary | Parameters |
|---|---|---|---|
| GET | `/api/v1/business-types` | Business Types |  |
| POST | `/api/v1/chat` | Chat | JSON body |
| GET | `/api/v1/chat/status` | Chat Status |  |
| GET | `/api/v1/compare` | Compare | `indicator`, `entities`, `year`? |
| POST | `/api/v1/feedback` | Post Feedback | JSON body |
| GET | `/api/v1/forecast-targets` | Forecast Targets |  |
| GET | `/api/v1/forecast/{indicator}/{level}/{soato}` | Forecast | `indicator`, `level`, `soato`, `horizon`? |
| GET | `/api/v1/geo/districts` | Geo Districts | `metric`?, `region`?, `year`? |
| GET | `/api/v1/geo/regions` | Geo Regions | `metric`?, `year`? |
| GET | `/api/v1/health` | Health |  |
| GET | `/api/v1/indicators` | Indicators | `category`? |
| GET | `/api/v1/monitoring/agent` | Monitoring Agent | `days`? |
| GET | `/api/v1/monitoring/data` | Monitoring Data |  |
| GET | `/api/v1/monitoring/models` | Monitoring Models |  |
| GET | `/api/v1/monitoring/recommendations` | Monitoring Recommendations |  |
| GET | `/api/v1/overview` | Overview |  |
| POST | `/api/v1/recommend` | Recommend | JSON body |
| GET | `/api/v1/regions` | Regions |  |
| GET | `/api/v1/regions/{soato}/districts` | Districts | `soato` |
| GET | `/api/v1/statistics` | Statistics | `indicator`, `level`?, `year`?, `region`? |
| GET | `/api/v1/territories/search` | Territory Search | `q`, `level`? |
| GET | `/api/v1/timeseries/{indicator}/{level}/{soato}` | Timeseries | `indicator`, `level`, `soato` |
| GET | `/health` | Health |  |

## Chat (SSE)

`POST /api/v1/chat` with `{messages: [{role, content}]}` streams server-sent events:

| Event | Data |
|---|---|
| `tool_call` | `{name, label, args}` — a tool the agent is calling |
| `tool_result` | `{name, ok}` |
| `token` | `{text}` — a piece of the markdown answer |
| `verification` | `{checked, unsupported[]}` — numbers not found in any tool result |
| `result` | `{request_id, map_focus{level, soatos[], region}, recommendation, is_synthetic}` |
| `done` | `{tools[], mode}` — `mode` is `llm` or `fallback` (no OpenAI key) |
| `error` | `{message}` |

## Example

```powershell
curl -X POST http://localhost:8000/api/v1/recommend -H "Content-Type: application/json" -d "{\"business_type\":\"pharmacy\",\"region\":\"1730\"}"
```
