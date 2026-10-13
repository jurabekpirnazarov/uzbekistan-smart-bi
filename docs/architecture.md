# Architecture

## Components

```mermaid
flowchart LR
  subgraph Sources
    SIAT[(SIAT / stat.uz<br/>SDMX JSON)]
    GEO[(Boundaries<br/>geoBoundaries, dirixtt)]
  end
  subgraph Pipelines
    ING[siat_ingest.py] --> LOAD[load_siat.py]
    REF[load_reference.py]
    FEAT[ml/features] --> TRAIN[ml/forecasting]
    RAGI[rag/ingest.py]
  end
  SIAT --> ING
  GEO --> REF
  LOAD & REF --> DB[(PostgreSQL 16<br/>+ PostGIS)]
  DB --> FEAT --> DB
  TRAIN --> DB
  TRAIN --> MLF[MLflow]
  RAGI --> DB
  subgraph Backend
    SVC[app/services<br/>the only business logic]
    API[FastAPI routers] --> SVC
    AG[AI agent<br/>LLM or rule-based] --> SVC
    MCP[MCP server] --> SVC
    SVC --> ML[ml/scoring, ml/forecasting]
  end
  DB <--> SVC
  UI[React + MapLibre<br/>dashboard, 3D map, chat] -- HTTP / SSE --> API
  OAI[OpenAI API] <-.-> AG
  PROM[Prometheus] -- /metrics --> API
  PROM --> GRAF[Grafana]
  MON[monitoring/drift.py] --> DB
```

Routers, MCP tools and agent tools are thin wrappers over `backend/app/services` and `ml/`;
calculation logic is never duplicated.

## Data flow

```mermaid
flowchart TD
  A[SIAT dataset JSON] -->|normalise, sha256| B[data/processed/*.csv]
  B -->|indicator_map.yaml: internal codes, unit multipliers| C[observations]
  C --> D[features: growth, per-capita, ratios, region context]
  D --> E[Business Opportunity Score]
  C --> F[backtest → best model → predictions + intervals]
  F --> D
  E & C & F --> G[API · MCP · agent]
  G --> H[UI: map, recommend, forecast, chat]
```

## Agent sequence

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Chat panel
  participant API as /api/v1/chat (SSE)
  participant AG as Agent
  participant T as Tools (services)
  participant V as Verifier
  U->>UI: "Where should I open a bakery in Fergana?"
  UI->>API: POST messages
  API->>AG: language = detect(question)
  alt OPENAI_API_KEY set
    AG->>AG: LLM chooses tools (max 8 rounds)
  else no key
    AG->>AG: keyword intent → fixed plan
  end
  AG->>T: calculate_business_score(bakery, 1730)
  T-->>AG: scores + breakdown + sources
  AG-->>UI: event tool_call / tool_result
  AG-->>UI: event token … (answer: statistics / model prediction / interpretation / sources)
  AG->>V: every number in the answer ∈ tool results?
  V-->>UI: event verification {checked, unsupported}
  AG-->>UI: event result {map_focus, request_id}
  AG->>API: log agent_runs + agent_tool_calls + metrics
```

## Deployment

```mermaid
flowchart LR
  subgraph "docker compose (server)"
    FE[frontend nginx :8080] --> BE[backend :8000]
    BE --> PG[(db: postgis + pgvector :5432)]
    MCPS[mcp :8100] --> PG
    W[worker: ingest/seed/features/train/eval]
    W --> PG
    ML[mlflow :5000]
    P[prometheus :9090] --> BE & MCPS
    G[grafana :3000] --> P & PG
  end
```

Local development without Docker (`python manage.py dev`) runs the same processes directly: portable
PostgreSQL + PostGIS in `.tools/`, uvicorn on :8000, Vite on :5174, the MCP server on :8100 and the MLflow
UI on :5000. See `docs/runbook.md`.
