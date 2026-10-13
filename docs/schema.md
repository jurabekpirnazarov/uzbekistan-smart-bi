# Database schema

_Generated from `backend/app/db/models.py` by `python -m app.db.schema_doc`. PostgreSQL 16 + PostGIS; migrations in `backend/alembic/versions/` (`python manage.py migrate`)._

Solid lines are foreign keys; dotted lines are logical links by code (SOATO / indicator code / request id).

```mermaid
erDiagram
  data_sources {
    integer id PK
    string name
    text url
    string kind
    text license
    datetime retrieved_at
  }
  regions {
    integer id PK
    string soato_code
    text name_en
    text name_uz
    text name_ru
    double centroid_lat
    double centroid_lon
    boolean geom_approx
    geometry geom
  }
  districts {
    integer id PK
    string soato_code
    integer region_id FK
    text name_en
    text name_uz
    text name_ru
    string kind
    double centroid_lat
    double centroid_lon
    boolean geom_approx
    geometry geom
  }
  indicators {
    integer id PK
    string code
    text name_en
    string category
    string unit
    string source_unit
    double unit_multiplier
    string frequency
    boolean additive
    boolean higher_is_better
    integer siat_dataset_id
    text source_name
    boolean auto_added
  }
  observations {
    bigint id PK
    integer indicator_id FK
    string level
    integer region_id FK
    integer district_id FK
    int year
    int quarter
    int month
    string period_label
    double value
    string unit
    integer source_id FK
    text source_url
    datetime retrieved_at
    string raw_sha256
    boolean is_synthetic
    datetime ingested_at
  }
  ingestion_runs {
    integer id PK
    integer source_id FK
    datetime started_at
    datetime finished_at
    string status
    integer datasets_ok
    integer rows_in
    integer rows_loaded
    integer rows_rejected
    text error
  }
  features {
    bigint id PK
    string name
    string level
    integer region_id FK
    integer district_id FK
    int year
    double value
    boolean is_synthetic
    string quality_flag
    json lineage
    string feature_version
    datetime computed_at
  }
  recommendations {
    integer id PK
    string request_id
    string business_type
    string scope_level
    string region_soato
    string target
    string data_mode
    json top
    json result
    datetime created_at
  }
  predictions {
    bigint id PK
    string run_id
    string indicator_code
    string level
    string soato
    string model
    int origin_year
    int year
    int horizon
    double yhat
    double lo80
    double hi80
    double lo95
    double hi95
    int history_points
    boolean low_confidence
    datetime created_at
  }
  model_metrics {
    bigint id PK
    string run_id
    string kind
    string split
    string indicator_code
    string level
    string model
    int horizon
    string metric
    double value
    boolean is_selected
    datetime created_at
  }
  agent_runs {
    integer id PK
    string request_id
    datetime created_at
    text question
    string lang
    string intent
    string mode
    string model
    string status
    integer latency_ms
    integer tokens_in
    integer tokens_out
    double cost_usd
    integer tool_count
    integer verification_failures
    text answer
  }
  agent_tool_calls {
    bigint id PK
    integer run_id FK
    string name
    json args
    boolean ok
    integer latency_ms
    datetime created_at
  }
  feedback {
    integer id PK
    string request_id
    string target
    int rating
    text comment
    datetime created_at
  }
  rag_chunks {
    integer id PK
    string doc_id
    text title
    text source_url
    integer chunk_index
    text content
    json embedding
    tsvector tsv
  }
  pipeline_runs {
    integer id PK
    string trigger
    datetime started_at
    datetime finished_at
    string status
    integer datasets_checked
    json datasets_changed
    json datasets_added
    json steps
    text error
  }
  monitor_metrics {
    bigint id PK
    string name
    json labels
    double value
    datetime created_at
  }
  regions ||--o{ districts : "region_id"
  indicators ||--o{ observations : "indicator_id"
  data_sources ||--o{ observations : "source_id"
  regions ||--o{ observations : "region_id"
  districts ||--o{ observations : "district_id"
  data_sources ||--o{ ingestion_runs : "source_id"
  regions ||--o{ features : "region_id"
  districts ||--o{ features : "district_id"
  agent_runs ||--o{ agent_tool_calls : "run_id"
  indicators ||..o{ predictions : "indicator_code"
  regions ||..o{ recommendations : "region_soato"
  agent_runs ||..o{ feedback : "request_id"
```

## Official data (warehouse)

### `data_sources`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `name` | varchar(64) | no |  |
| `url` | text | yes |  |
| `kind` | varchar(16) | no |  |
| `license` | text | yes |  |
| `retrieved_at` | datetime | yes |  |

Constraints: unique (name)

### `regions`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `soato_code` | varchar(16) | no |  |
| `name_en` | text | no |  |
| `name_uz` | text | yes |  |
| `name_ru` | text | yes |  |
| `centroid_lat` | double | yes |  |
| `centroid_lon` | double | yes |  |
| `geom_approx` | boolean | no |  |
| `geom` | geometry(MultiPolygon,4326) | yes | PostGIS boundary (raw SQL) |

Constraints: unique (soato_code)

### `districts`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `soato_code` | varchar(16) | no |  |
| `region_id` | integer | no | FK → regions.id |
| `name_en` | text | no |  |
| `name_uz` | text | yes |  |
| `name_ru` | text | yes |  |
| `kind` | varchar(16) | no |  |
| `centroid_lat` | double | yes |  |
| `centroid_lon` | double | yes |  |
| `geom_approx` | boolean | no |  |
| `geom` | geometry(MultiPolygon,4326) | yes | PostGIS boundary (NULL when approximate) (raw SQL) |

Constraints: unique (soato_code) · index (region_id)

### `indicators`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `code` | varchar(64) | no |  |
| `name_en` | text | no |  |
| `category` | varchar(32) | no |  |
| `unit` | varchar(64) | no |  |
| `source_unit` | varchar(64) | yes |  |
| `unit_multiplier` | double | no |  |
| `frequency` | varchar(16) | no |  |
| `additive` | boolean | no |  |
| `higher_is_better` | boolean | no |  |
| `siat_dataset_id` | integer | yes |  |
| `source_name` | text | yes |  |
| `auto_added` | boolean | no |  |

Constraints: unique (code)

### `observations`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `indicator_id` | integer | no | FK → indicators.id |
| `level` | varchar(16) | no |  |
| `region_id` | integer | yes | FK → regions.id |
| `district_id` | integer | yes | FK → districts.id |
| `year` | smallint | no |  |
| `quarter` | smallint | yes |  |
| `month` | smallint | yes |  |
| `period_label` | varchar(32) | no |  |
| `value` | double | no |  |
| `unit` | varchar(64) | no |  |
| `source_id` | integer | no | FK → data_sources.id |
| `source_url` | text | yes |  |
| `retrieved_at` | datetime | yes |  |
| `raw_sha256` | varchar(64) | yes |  |
| `is_synthetic` | boolean | no |  |
| `ingested_at` | datetime | no |  |

Constraints: unique (indicator_id, level, region_id, district_id, year, quarter, month, source_id) · index (district_id) · index (indicator_id, level, year) · index (region_id)

### `ingestion_runs`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `source_id` | integer | yes | FK → data_sources.id |
| `started_at` | datetime | no |  |
| `finished_at` | datetime | yes |  |
| `status` | varchar(16) | no |  |
| `datasets_ok` | integer | no |  |
| `rows_in` | integer | no |  |
| `rows_loaded` | integer | no |  |
| `rows_rejected` | integer | no |  |
| `error` | text | yes |  |

## Analytics

### `features`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `name` | varchar(64) | no |  |
| `level` | varchar(16) | no |  |
| `region_id` | integer | yes | FK → regions.id |
| `district_id` | integer | yes | FK → districts.id |
| `year` | smallint | no |  |
| `value` | double | yes |  |
| `is_synthetic` | boolean | no |  |
| `quality_flag` | varchar(64) | yes |  |
| `lineage` | json | yes |  |
| `feature_version` | varchar(16) | no |  |
| `computed_at` | datetime | no |  |

Constraints: unique (name, level, region_id, district_id, year) · index (name, level, year)

### `recommendations`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `request_id` | varchar(64) | no |  |
| `business_type` | varchar(64) | no |  |
| `scope_level` | varchar(16) | no |  |
| `region_soato` | varchar(16) | yes |  |
| `target` | varchar(32) | yes |  |
| `data_mode` | varchar(16) | no |  |
| `top` | json | yes |  |
| `result` | json | no |  |
| `created_at` | datetime | no |  |

Constraints: index (business_type) · index (request_id)

### `predictions`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `run_id` | varchar(32) | no |  |
| `indicator_code` | varchar(64) | no |  |
| `level` | varchar(16) | no |  |
| `soato` | varchar(16) | no |  |
| `model` | varchar(32) | no |  |
| `origin_year` | smallint | no |  |
| `year` | smallint | no |  |
| `horizon` | smallint | no |  |
| `yhat` | double | no |  |
| `lo80` | double | yes |  |
| `hi80` | double | yes |  |
| `lo95` | double | yes |  |
| `hi95` | double | yes |  |
| `history_points` | smallint | no |  |
| `low_confidence` | boolean | no |  |
| `created_at` | datetime | no |  |

Constraints: index (indicator_code, level, soato)

### `model_metrics`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `run_id` | varchar(32) | no |  |
| `kind` | varchar(16) | no |  |
| `split` | varchar(16) | no |  |
| `indicator_code` | varchar(64) | yes |  |
| `level` | varchar(16) | yes |  |
| `model` | varchar(64) | yes |  |
| `horizon` | smallint | yes |  |
| `metric` | varchar(32) | no |  |
| `value` | double | yes |  |
| `is_selected` | boolean | no |  |
| `created_at` | datetime | no |  |

Constraints: index (kind, created_at)

## AI agent and RAG

### `agent_runs`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `request_id` | varchar(64) | no |  |
| `created_at` | datetime | no |  |
| `question` | text | no |  |
| `lang` | varchar(4) | no |  |
| `intent` | varchar(32) | yes |  |
| `mode` | varchar(16) | no |  |
| `model` | varchar(64) | yes |  |
| `status` | varchar(16) | no |  |
| `latency_ms` | integer | no |  |
| `tokens_in` | integer | no |  |
| `tokens_out` | integer | no |  |
| `cost_usd` | double | no |  |
| `tool_count` | integer | no |  |
| `verification_failures` | integer | no |  |
| `answer` | text | yes |  |

Constraints: index (request_id) · index (created_at)

### `agent_tool_calls`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `run_id` | integer | no | FK → agent_runs.id |
| `name` | varchar(64) | no |  |
| `args` | json | yes |  |
| `ok` | boolean | no |  |
| `latency_ms` | integer | no |  |
| `created_at` | datetime | no |  |

Constraints: index (run_id)

### `feedback`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `request_id` | varchar(64) | yes |  |
| `target` | varchar(16) | no |  |
| `rating` | smallint | no |  |
| `comment` | text | yes |  |
| `created_at` | datetime | no |  |

Constraints: index (request_id)

### `rag_chunks`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `doc_id` | varchar(128) | no |  |
| `title` | text | no |  |
| `source_url` | text | yes |  |
| `chunk_index` | integer | no |  |
| `content` | text | no |  |
| `embedding` | json | yes |  |
| `tsv` | tsvector | yes | generated full-text vector (BM25-style search) (raw SQL) |

Constraints: index (doc_id)

## Operations

### `pipeline_runs`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | integer | no | PK |
| `trigger` | varchar(16) | no |  |
| `started_at` | datetime | no |  |
| `finished_at` | datetime | yes |  |
| `status` | varchar(16) | no |  |
| `datasets_checked` | integer | no |  |
| `datasets_changed` | json | yes |  |
| `datasets_added` | json | yes |  |
| `steps` | json | yes |  |
| `error` | text | yes |  |

Constraints: index (started_at)

### `monitor_metrics`

| Column | Type | Null | Key / notes |
|---|---|---|---|
| `id` | bigint | no | PK |
| `name` | varchar(64) | no |  |
| `labels` | json | no |  |
| `value` | double | yes |  |
| `created_at` | datetime | no |  |

Constraints: index (name, created_at)
