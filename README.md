# Wealthy Property Portfolio Engine

**WealthNexus Backend** — a FastAPI service for tracking residential property held
*personally*, inside *superannuation*, or through a *company entity*.

It takes an address (or listing URL) plus a purchase price, enriches it with a
current valuation from **Domain.com.au**, and stores the result as part of a
multi-entity portfolio.

---

## Table of Contents

- [Architecture](#architecture)
- [Request lifecycle](#request-lifecycle)
- [Endpoint error paths](#endpoint-error-paths)
- [Domain.com.au integration](#domaincomau-integration)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [API reference](#api-reference)
- [Data model](#data-model)
- [Design principles](#design-principles)
- [Testing](#testing)
- [Deployment](#deployment)
- [Diagrams (Mermaid & PELE)](#diagrams-mermaid--pele)
- [Migration notes from v1](#migration-notes-from-v1)

---

## Architecture

Each layer has exactly one job, and dependencies point inwards only.

```mermaid
flowchart TD
    subgraph Client["Client tier"]
        UI["React / Mobile client"]
    end

    subgraph Api["API tier — FastAPI"]
        MAIN["app/main.py<br/>app factory, lifespan, health"]
        ROUTER["app/routers/portfolio.py<br/>HTTP endpoints"]
        AUTH["app/auth/dependencies.py<br/>bearer token → owner"]
        SCHEMAS["app/schemas.py<br/>Pydantic v2 contracts"]
    end

    subgraph DomainTier["Domain tier"]
        SERVICE["app/services/property_service.py<br/>valuation + honest fallback"]
        DC["app/services/domain_client.py<br/>Domain HTTP, timeout, retry"]
    end

    subgraph Infra["Infrastructure"]
        CONFIG["app/config.py<br/>Settings & secrets"]
        MODELS["app/models.py<br/>SQLAlchemy ORM"]
        DB[("PostgreSQL")]
        EXT["Domain.com.au<br/>developer API"]
    end

    UI -->|"HTTPS / JSON"| MAIN
    MAIN --> ROUTER
    ROUTER --> SCHEMAS
    ROUTER --> AUTH
    ROUTER --> SERVICE
    ROUTER --> MODELS
    SERVICE --> CONFIG
    SERVICE --> DC
    MODELS --> DB
    DC -->|"HTTPS + x-api-key"| EXT

    classDef store fill:#1e293b,stroke:#38bdf8,color:#f8fafc
    classDef svc fill:#1e3a5f,stroke:#38bdf8,color:#f8fafc
    class DB,EXT store
    class SERVICE,DC,SCHEMAS,ROUTER,AUTH svc
```

| Layer | File | Responsibility | Knows about |
|---|---|---|---|
| Config | `app/config.py` | Secrets, URLs, feature flags | nothing else |
| Contracts | `app/schemas.py` | What valid data looks like | nothing else |
| Auth | `app/auth/dependencies.py` | Bearer token → owner | models, db |
| Domain | `app/services/property_service.py` | Doing the actual work | config, schemas, domain client |
| Provider | `app/services/domain_client.py` | Talking to Domain.com.au | nothing else |
| Persistence | `app/models.py` | The database tables | db only |
| Transport | `app/routers/portfolio.py` | HTTP in / HTTP out | schemas, service, models, db |
| Bootstrap | `app/main.py` | Wiring, middleware, health | everything |

---

## Request lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as Router
    participant S as PropertyService
    participant D as Domain API
    participant DB as PostgreSQL

    C->>R: POST /api/portfolio/properties (Bearer token)
    R->>R: Validate body against PropertyCreateRequest
    R->>R: Resolve token → owner
    R->>S: get_valuation(query, purchase_price)
    S->>D: GET /v1/properties/_suggest (x-api-key)
    D-->>S: [{id, address, relativeScore}]
    S->>D: GET /v1/properties/{id}/priceEstimate
    D-->>S: midPrice, lowerPrice, upperPrice, priceConfidence
    S->>D: GET /v1/properties/{id}
    D-->>S: address, history.sales[], canonicalUrl
    S->>D: GET /v1/properties/{id}/rentalEstimate
    D-->>S: weeklyRentEstimate
    S-->>R: ValuationResult — provenance: "Domain.com.au AVM"

    R->>DB: INSERT INTO properties
    R->>DB: COMMIT
    R->>DB: SELECT (refresh — picks up generated id)
    R-->>C: 201 Created — PropertyResponse
```

When Domain cannot be reached, the service degrades to an algorithmic estimate
and labels it as one — see [Domain.com.au integration](#domaincomau-integration).

---

## Endpoint error paths

```mermaid
flowchart TD
    A["POST /api/portfolio/properties"] --> B{"Body matches<br/>PropertyCreateRequest?"}
    B -->|"No"| C["422 Unprocessable Entity<br/>field-level errors"]
    B -->|"Yes"| D{"Bearer token valid?"}
    D -->|"No"| C2["401 Unauthorized"]
    D -->|"Yes"| E["PropertyService.get_valuation()"]
    E --> F{"Domain reachable?"}
    F -->|"Yes"| G["ValuationResult<br/>provenance: Domain.com.au AVM"]
    F -->|"No / timeout / 5xx"| H{"Fallback allowed?"}
    H -->|"Yes"| I["ValuationResult<br/>provenance: algorithmic estimate"]
    H -->|"No"| J["502 Bad Gateway"]
    G --> K{"Duplicate property?"}
    I --> K
    K -->|"Yes"| L["409 Conflict<br/>rollback"]
    K -->|"No"| M["INSERT + COMMIT"]
    M --> N["201 Created<br/>PropertyResponse"]
```

---

## Domain.com.au integration

The valuation provider is Domain's official developer API
(`developer.domain.com.au`), reached over HTTPS at
`https://api.domain.com.au`.

### Authentication

The key is sent as the **`x-api-key`** header. Domain issues keys of the form
`key_…` from the developer portal; OAuth 2.0 client-credentials tokens are
also supported (`WEALTHY_DOMAIN_AUTH_MODE=bearer`, sent as
`Authorization: Bearer …`).

```bash
WEALTHY_DOMAIN_API_KEY=key_your_key_here
WEALTHY_DOMAIN_AUTH_MODE=api_key
```

> A Domain subscription is required, and the project must have the relevant
> **API packages** granted. The endpoints below need
> `api_properties_read` (suggest, property, price estimate) and
> `api_avm_read` (rental estimate). Without the rental package the rent is
> simply absent — the valuation still succeeds.

### Endpoints used

| Endpoint | Scope | What it gives us |
|---|---|---|
| `GET /v1/properties/_suggest?terms=…` | `api_properties_read` | Resolves an address string to a Domain `propertyId` (best `relativeScore` wins) |
| `GET /v1/properties/{id}` | `api_properties_read` | The **resolved** address, `canonicalUrl`, and `history.sales[]` for the last-sold date |
| `GET /v1/properties/{id}/priceEstimate` | `api_properties_read` | `midPrice` / `lowerPrice` / `upperPrice` and `priceConfidence` — the AVM |
| `GET /v1/properties/{id}/rentalEstimate` | `api_avm_read` | `weeklyRentEstimate` |

A Domain listing URL is handled directly: the property id is parsed out of
`…/property-profile/<slug>-12345678`, so no suggestion round-trip is needed.

### The fallback, and why it labels itself

If Domain is unreachable, rejects the credentials, or has no record for the
address, the service falls back to a 5% uplift on the purchase price and
records the provenance as:

```
algorithmic estimate (5% uplift — NOT an AVM)
```

It never borrows another provider's name. A fallback that impersonates a real
provider is worse than no fallback, because it is silently wrong and it looks
authoritative.

Set `WEALTHY_STRICT_PROVIDER=true` to disable the fallback — a provider
failure then returns `502` instead of a number the service cannot attribute.
That mode also makes a missing API key a startup error rather than a warning.

### Retry and timeout

Every call carries an explicit `(connect, read)` timeout and a bounded retry
policy (`WEALTHY_DOMAIN_RETRIES`, with backoff) for `429` and `5xx` responses.
The calls are blocking `requests`, so the routes that call them are `def`, not
`async def` — FastAPI runs those in a threadpool.

---

## Tech stack

| Layer | Choice | Version | Why |
|---|---|---|---|
| Web framework | FastAPI | 0.115+ | Async, auto-validated request bodies, OpenAPI docs for free |
| Validation | Pydantic v2 | 2.x | One schema layer for request *and* response; `Decimal` support |
| Settings | pydantic-settings | 2.x | Env vars + `.env` with type coercion |
| ORM | SQLAlchemy | 2.0 | Typed `Mapped[]` columns, `Numeric` for money |
| Migrations | Alembic | 1.13+ | Real schema evolution — `create_all()` cannot alter tables |
| Database | PostgreSQL | 15+ | `NUMERIC` money columns, JSONB, row-level security |
| HTTP client | requests + urllib3 Retry | — | Connection pooling, retries, explicit timeouts |
| Validation (tests) | pytest + responses | — | Fake external HTTP without monkeypatching internals |

---

## Project layout

```
app/
├── __init__.py
├── main.py                       # app factory, lifespan, CORS, health checks
├── config.py                     # Settings (secrets, URLs, flags)
├── database.py                   # engine, SessionLocal, Base, get_db
├── models.py                     # UserModel, PropertyModel (SQLAlchemy ORM)
├── schemas.py                    # Pydantic request/response models
├── auth/
│   ├── __init__.py
│   └── dependencies.py           # get_current_user, require_user
├── routers/
│   ├── __init__.py
│   ├── auth.py                   # POST /auth/token, GET /auth/whoami
│   └── portfolio.py              # /api/portfolio/*
├── services/
│   ├── __init__.py
│   ├── domain_client.py          # Domain.com.au HTTP client
│   └── property_service.py       # AVM lookup + estimate fallback
├── static/
│   └── index.html                # the WealthNexus frontend
└── tests/
    ├── __init__.py
    ├── conftest.py               # db session override, client fixture
    ├── test_portfolio_router.py
    └── test_property_service.py

alembic/
├── env.py                        # reads URL from settings
├── script.py.mako
└── versions/
    └── 0001_initial_schema.py

legacy/
└── v1_app.py                     # the original single-file app, kept for reference
portfolio_tree.py                 # standalone graphviz portfolio diagram
alembic.ini
pyproject.toml                    # `pip install -e ".[dev]"`
.env                             # gitignored
.env.example                     # committed
```

---

## Quickstart

### 1. Prerequisites

- Python **3.11+**
- PostgreSQL **15+** running locally (or via Docker)
- A Domain.com.au developer API key *(optional — without one the app serves
  labelled estimates)*

### 2. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` — at minimum set `WEALTHY_DATABASE_URL`. Add
`WEALTHY_DOMAIN_API_KEY` when you have a key.

### 4. Create the schema

```bash
alembic upgrade head
```

> `create_all()` is **not** used in production. It can only ever `CREATE TABLE` —
> it can never add a column, change a type, or add a constraint. Alembic owns
> the schema; `create_all` is a dev-only convenience behind
> `WEALTHY_AUTO_CREATE_TABLES=true`.

### 5. Run

```bash
uvicorn app.main:app --reload
```

| URL | What |
|---|---|
| `http://localhost:8000/` | The WealthNexus frontend |
| `http://localhost:8000/docs` | Swagger UI (dev only) |
| `http://localhost:8000/redoc` | ReDoc (dev only) |
| `http://localhost:8000/health/live` | Liveness — no dependencies |
| `http://localhost:8000/health/ready` | Readiness — actually runs `SELECT 1` |

### 6. Get a token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com"}' | jq -r .access_token)
```

The token is shown once. Only its SHA-256 hash is stored.

### 7. Try it

```bash
curl -X POST http://localhost:8000/api/portfolio/properties \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "25 King St, Melbourne VIC 3000",
       "purchase_price": 500000,
       "entity_type": "personal"}'
```

---

## Configuration

All settings are read from environment variables, falling back to `.env`.

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `WEALTHY_APP_NAME` | `str` | `Wealthy Property Portfolio Engine` | no | Display name |
| `WEALTHY_APP_VERSION` | `str` | `7.1.0` | no | Reported in the OpenAPI spec |
| `WEALTHY_DEBUG` | `bool` | `False` | no | `True` in dev only — enables tracebacks and `/docs` |
| `WEALTHY_DATABASE_URL` | `str` | — | **yes** | `postgresql+psycopg://user:pass@host:5432/db` |
| `WEALTHY_AUTO_CREATE_TABLES` | `bool` | `False` | no | Dev convenience only |
| `WEALTHY_DOMAIN_API_KEY` | `SecretStr` | — | no\* | Bearer token for the AVM provider |
| `WEALTHY_DOMAIN_AUTH_MODE` | `str` | `api_key` | no | `api_key` (x-api-key) or `bearer` |
| `WEALTHY_DOMAIN_BASE_URL` | `str` | `https://api.domain.com.au` | no | |
| `WEALTHY_DOMAIN_TIMEOUT` | `float` | `10.0` | no | Read timeout, seconds |
| `WEALTHY_DOMAIN_CONNECT_TIMEOUT` | `float` | `3.05` | no | Connect timeout, seconds |
| `WEALTHY_DOMAIN_RETRIES` | `int` | `2` | no | Retries for `429`/`5xx` |
| `WEALTHY_ALLOW_ESTIMATE_FALLBACK` | `bool` | `True` | no | Degrade to an estimate when Domain is down |
| `WEALTHY_STRICT_PROVIDER` | `bool` | `False` | no | Return `502` instead of degrading |
| `WEALTHY_CORS_ORIGINS` | `list[str]` | `["http://localhost:5173"]` | no | Explicit origins — never `*` with credentials |

\* `WEALTHY_DOMAIN_API_KEY` is required in practice. It is only optional at
the settings layer so the app can boot in a demo without credentials; when
`WEALTHY_STRICT_PROVIDER=true` a missing key is a **startup error**.

**Resolution order** (highest priority first):

1. Environment variable
2. `.env` file
3. The default in `config.py`

Values are coerced and validated on load. A bad value fails **at startup**, not
at 3 AM. A missing required value raises `ValidationError` immediately — the
app refuses to start rather than silently connecting to the wrong database.

---

## Authentication

Every portfolio endpoint requires a bearer token that maps to an owner.

```http
Authorization: Bearer wpx_9BSC9LJ0W1...
```

- `POST /auth/token` — exchanges an email for a token, creating the owner on
  first use. This is a **local-development convenience**; a production
  deployment would verify the email before minting a token.
- The token is 32 bytes of random data, URL-safe. Only its SHA-256 hash is
  stored — it is shown exactly once, at issue time.
- `GET /auth/whoami` — who the presented token belongs to.

Every property row carries an `owner_id` foreign key. Every query is filtered
by it. One owner can never read, write or delete another owner's rows — a
request for someone else's property returns `404`, not `403`, so the endpoint
does not confirm that the row exists.

---

## API reference

| Method | Path | Request body | Success | Errors | Auth |
|---|---|---|---|---|---|
| `GET` | `/api/portfolio/properties` | — | `200` · `list[PropertyResponse]` | — | ✅ |
| `POST` | `/api/portfolio/properties` | `PropertyCreateRequest` | `201` · `PropertyResponse` | `422` invalid body · `409` duplicate · `502` provider down | ✅ |
| `GET` | `/api/portfolio/properties/{id}` | — | `200` · `PropertyResponse` | `404` not found | ✅ |
| `POST` | `/api/portfolio/properties/{id}/transfer` | `EntityTransferRequest` | `200` · `PropertyResponse` | `404` not found · `422` invalid entity | ✅ |
| `DELETE` | `/api/portfolio/properties/{id}` | — | `204` · no content | `404` not found | ✅ |
| `POST` | `/auth/token` | `TokenRequest` | `201` · `TokenResponse` | `422` invalid body | — |
| `GET` | `/auth/whoami` | — | `200` | `401` | ✅ |
| `GET` | `/` | — | `200` · HTML | — | — |
| `GET` | `/health/live` | — | `200` | — | — |
| `GET` | `/health/ready` | — | `200` / `503` | — | — |

The list endpoint is paginated: `?limit=` (1–200, default 50) and `?offset=`.

Every response is filtered through a `response_model`. Columns that are not
listed in the Pydantic schema **cannot leak** to a client — including internal
notes, raw provider payloads, the owner's `owner_id`, and other users' rows.

### `PropertyCreateRequest`

| Field | Type | Rules |
|---|---|---|
| `query` | `str` | required, 3–500 chars, stripped |
| `purchase_price` | `Decimal` | required, `> 0`, max 14 digits / 2 dp |
| `entity_type` | `EntityType` | required — `personal` \| `super` \| `company` |

### `PropertyResponse`

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Database-generated |
| `name` | `str` | **Resolved** address, not the raw user input |
| `entity_type` | `EntityType` | |
| `purchase_price` | `Decimal` | |
| `current_value` | `Decimal` | |
| `last_sold_date` | `date \| None` | Real date, not a string |
| `current_rent` | `Decimal \| None` | Weekly amount, not `"Rent $580/wk"` |
| `provenance_source` | `str \| None` | **States what actually produced the number** |
| `source_url` | `HttpUrl \| None` | Validated URL |

---

## Data model

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` | PK, autoincrement |
| `email` | `String(320)` | Unique |
| `display_name` | `String(120)` | |
| `token_hash` | `String(128)` | Unique — SHA-256 of the bearer token |
| `is_active` | `Boolean` | |
| `created_at` | `DateTime(tz)` | Server default |

### `properties`

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` | PK, autoincrement |
| `owner_id` | `Integer` | FK → users — every row is scoped to an owner |
| `name` | `String(255)` | Resolved property address |
| `entity_type` | `String(32)` | `personal` / `super` / `company` |
| `purchase_price` | `Numeric(14, 2)` | Exact decimal — never `float` |
| `current_value` | `Numeric(14, 2)` | |
| `last_sold_date` | `Date` | |
| `current_rent` | `Numeric(10, 2)` | |
| `provenance_source` | `String(128)` | |
| `source_url` | `String(512)` | |
| `domain_property_id` | `String(64)` | Domain's own id for the property |
| `created_at` | `DateTime(tz)` | Server default |
| `updated_at` | `DateTime(tz)` | `onupdate` |

A unique constraint on `(owner_id, name)` backs the `409 Conflict` path.

---

## Design principles

### 1. Never claim more than you know

`provenance_source` records **what actually produced the number**. An estimate
says *"algorithmic estimate (5% uplift — NOT an AVM)"*. A health endpoint says
*"database: connected"* only after a real `SELECT 1` succeeds.

> A fallback that impersonates a real provider is worse than no fallback,
> because it is silently wrong and it looks authoritative.

### 2. Money is `Decimal`, never `float`

```python
0.1 + 0.2 == 0.30000000000000004   # 💀
```

Portfolios are totalled. Totals compound errors. `NUMERIC` columns and
`Decimal` fields, all the way through. The frontend does its display
arithmetic in integer cents for the same reason.

### 3. Dates are `date`, never `str`

`"15 Oct 2022"` parses; `"banana"` does not. Type it once, validate once.

### 4. Fail fast at startup

A missing API key or a malformed `DATABASE_URL` crashes the boot with a clear
message — rather than failing at the first request in production.

### 5. No unbounded I/O

Every outbound HTTP call has a `timeout`, a retry policy, and a fallback. The
list endpoint is paginated. `create_all()` runs inside `lifespan`, never at
import time, so a dead database produces a `503` — not a crash loop.

### 6. Blocking work belongs in `def`, not `async def`

FastAPI runs sync endpoints in a threadpool. A blocking `requests.post` inside
an `async def` endpoint stalls the entire event loop. If you go async, use
`httpx.AsyncClient`.

---

## Testing

```bash
pytest                              # everything
pytest --cov=app --cov-report=term  # with coverage
```

The suite covers the paths that matter:

| Test | Asserts |
|---|---|
| `test_api_success` | An AVM response is mapped into a `ValuationResult` |
| `test_api_failure_falls_back` | A 500 from the provider degrades to the estimate |
| `test_estimate_is_honest` | The fallback's `provenance_source` says it is *not* an AVM |
| `test_response_model_filters` | Internal columns never appear in the JSON |
| `test_owner_isolation` | User A cannot read or delete user B's property |
| `test_transient_500_is_retried` | A `5xx` is retried before it is given up on |
| `test_listing_url_skips_the_suggest_endpoint` | A listing URL goes straight to the property |
| `test_missing_rent_estimate_does_not_fail_the_valuation` | Enrichment failure does not sink the AVM |
| `test_duplicate_property_is_a_conflict` | The unique constraint backs the `409` |
| `test_provider_down_with_strict_mode_is_a_bad_gateway` | No fallback means no invented number |

The database is swapped via `app.dependency_overrides[get_db]` and the
valuation service via `app.dependency_overrides[get_property_service]` — the
routes themselves are never modified for tests.

The tests run against a **real PostgreSQL** database
(`WEALTHY_TEST_DATABASE_URL`, default `…/wealthnexus_test`), not SQLite:
SQLite would accept a float where PostgreSQL refuses it, so the tests would
pass against a schema the app never actually uses.

```bash
createdb wealthnexus_test
```

---

## Deployment

```bash
uvicorn app.main:app --workers 4 --proxy-headers --forwarded-allow-ips="*"
```

- Run `alembic upgrade head` **once**, before the app starts.
- Set `WEALTHY_DEBUG=false` — this also disables `/docs`, `/redoc` and
  `/openapi.json`.
- Set `WEALTHY_STRICT_PROVIDER=true` in production, so a provider outage
  returns `502` rather than an estimate nobody can attribute.
- Provide `WEALTHY_DOMAIN_API_KEY` and `WEALTHY_DATABASE_URL` as secrets,
  never as committed files.
- Point the orchestrator's health check at `/health/ready`, and its liveness
  probe at `/health/live`.
- Set `root_path` and `proxy_headers` if you sit behind a reverse proxy.

---

## Diagrams (Mermaid & PELE)

Every diagram in this README is authored in [Mermaid](https://mermaid.js.org)
syntax and rendered as a `mermaid` code fence.

```mermaid
flowchart LR
    A[Mermaid text] --> B{Readable<br/>anywhere?}
    B -->|Yes| C[SVG output]
```

### Which renderer?

| Renderer | Use when |
|---|---|
| **Mermaid.js** (default) | GitHub, GitLab, and Obsidian render `mermaid` fences themselves — zero configuration |
| **[PELE](https://pele.run)** | You host the docs and want a smaller, faster, dependency-free renderer |

[PELE](https://pele.run) is a **drop-in renderer replacement** for
Mermaid.js — *not* a new diagram language. The source syntax is unchanged, so
every `mermaid` fence in this file works with either renderer.

```bash
npm install pele
```

```ts
import { mount } from 'pele';

mount(document.querySelector('#diagram'), diagramSource);
```

```html
<script src="https://cdn.jsdelivr.net/npm/pele@1/dist/pele.global.js"></script>
<script>
  for (const el of document.querySelectorAll('pre.mermaid'))
    pele.mount(el, el.textContent);
</script>
```

Vendored figures from the project homepage: **230 kB** gzipped vs **1.6 MB**
for Mermaid.js, **0** runtime dependencies vs 23, and render times of
**0.05–0.3 ms** vs **6–82 ms**.

What changes when you swap the renderer:

| Behaviour | PELE |
|---|---|
| Syntax | Mermaid 12.1.0 — unchanged, all built-in diagram types supported |
| Layout | Its own engine — node positions and edge paths differ from Mermaid.js |
| Theming | CSS variables (`--pele-bg`, `--pele-fg`, …). Mermaid `themeVariables` do **not** apply |
| Plugins | External plugins (e.g. ZenUML) are not supported |
| Labels | SVG text with line breaks, bold, italic — arbitrary HTML labels are not supported |
| `click` handlers | Links work; JavaScript callbacks are ignored |
| Math (`$$…$$`) | Needs a `math` resolver — otherwise the TeX source is shown |
| Limits | 50,000 chars of source, 4,000,000 chars of SVG output, 5,000 edges |

### Rendering to SVG without a browser

```bash
npm install -g @jpmanson/pele-skill   # renders Mermaid → SVG headlessly
```

Useful in CI, for generating static assets, or for agents that need a diagram
as a file rather than as text.

---

## Migration notes from v1

The v1 codebase (kept at `legacy/v1_app.py`) carried several defects. This
table records the renames and behaviour changes so upgrading call sites is
mechanical.

| v1 | v2 | Reason |
|---|---|---|
| `fetch_vaulation_from_api` | `fetch_valuation` | Typo — the old name could not be called correctly |
| Single `fetch_*` method | `fetch_valuation` + `estimate_valuation` + `get_valuation` | One job per function |
| `provenance_source` always `"Domain.com.au AVM & CoreLogic RP Data"` | States the actual source | The fallback was impersonating a real provider |
| `current_rent: str` | `current_rent: Decimal \| None` | Rent had to be summable |
| `last_sold_date: str` | `last_sold_date: date \| None` | Dates had to be parseable |
| `purchase_price: float` | `purchase_price: Decimal` | Money must not drift |
| `entity_type: str` | `entity_type: EntityType` | Validation now matches the documentation |
| `Base.metadata.create_all()` at import | Alembic + `lifespan` | `create_all` cannot alter a schema |
| Landing page claiming "Database connected" | `/health/ready` that verifies it | The claim is now true, or absent |
| No CORS | `CORSMiddleware` with explicit origins | Browsers blocked every frontend request |
| `/docs` always public | Disabled unless `debug` | Attack-surface map |
| Hardcoded portfolio in the frontend | `GET /api/portfolio/properties` | The UI reads the database, not a literal |
| No auth | Bearer token → `owner_id` | One owner can never see another's rows |
| Fake "Confidence Score: 96.4%" | Real `provenance_source` | A made-up confidence number is a lie |
