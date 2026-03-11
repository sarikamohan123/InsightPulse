# SentimentPulse

A multi-tenant customer feedback aggregator. Ingest reviews from multiple
sources, run async LLM summarization jobs, and surface the top pain points
through a dashboard UI.

Built as a learning project demonstrating enterprise-grade backend patterns:
multi-tenancy, async task queues, provider abstractions, JWT auth, and a
full integration test suite.

---

## What It Does

1. **Ingest reviews** — upload a CSV or pull from simulated App Store, Google, or Twitter sources
2. **Trigger a summarization job** — selects a batch of reviews, dispatches to a Celery worker
3. **LLM extracts pain points** — the worker calls an LLM provider and writes a structured summary
4. **View results** — the frontend polls job status and displays the top pain points on completion

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI (Python 3.12), async SQLAlchemy 2.0 |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 16 |
| LLM | HuggingFace Inference API (Mistral-7B) or MockProvider |
| Auth | JWT — access tokens (15 min) + refresh tokens (7 days) |
| Frontend | React 18 + TypeScript + Vite |
| Server State | TanStack Query v5 |
| Client State | Zustand |
| Containerization | Docker Compose |
| Tests | pytest (integration + unit), Playwright (E2E) |

---

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 4.x+

### 1. Clone and configure

```bash
git clone <repo-url>
cd InsightPulse
cp backend/.env.example backend/.env
```

`HUGGINGFACE_API_KEY` in `.env` is optional. If left blank, a mock LLM
provider is used automatically — the full job flow works without an API key.

### 2. Start the stack

```bash
docker compose up --build
```

### 3. Apply database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4. Open the app

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| API docs (ReDoc) | http://localhost:8000/redoc |

Register an account to get started. The first user created for an organization
is automatically assigned the `admin` role.

---

## Running Tests

Create the test database once:

```bash
docker compose exec db psql -U postgres -c "CREATE DATABASE sentimentpulse_test;"
```

Run the test suite:

```bash
docker compose exec backend pytest
```

Run with coverage:

```bash
docker compose exec backend pytest --cov=app --cov-report=term-missing
```

---

## Project Structure

```
InsightPulse/
├── backend/
│   ├── app/
│   │   ├── api/           ← FastAPI routers + dependency injection
│   │   ├── core/          ← config, security, exceptions
│   │   ├── db/            ← session factory, base model
│   │   ├── models/        ← SQLAlchemy ORM models
│   │   ├── schemas/       ← Pydantic request/response schemas
│   │   ├── services/      ← business logic
│   │   ├── repositories/  ← data access layer (org isolation enforced here)
│   │   ├── providers/
│   │   │   ├── llm/       ← LLMProvider ABC + HuggingFace + Mock
│   │   │   └── sources/   ← SourceProvider ABC + CSV + simulated sources
│   │   └── workers/       ← Celery app + summarization task
│   └── tests/             ← pytest integration + unit tests
├── frontend/
│   └── src/
│       ├── api/           ← Axios functions
│       ├── hooks/         ← TanStack Query wrappers
│       ├── store/         ← Zustand auth store
│       ├── components/    ← UI components
│       └── pages/         ← route-level pages
├── docs/                  ← architecture and design documentation
├── docker-compose.yml
└── docker-compose.override.yml
```

---

## Key Design Decisions

**Multi-tenancy** — row-level isolation via `organization_id` on all
tenant-owned tables, enforced at the repository layer. No service or API
handler may query tenant data without supplying `organization_id`.

**Provider abstractions** — `LLMProvider` and `SourceProvider` are abstract
base classes. Swapping LLM providers or adding a new review source requires
only a new implementation file — no existing code changes.

**Dependency injection** — FastAPI's `Depends()` wires concrete providers at
the composition root (`api/deps.py`). Services depend on abstractions, never
on concrete classes. This makes every service unit-testable with mock injections.

**Async first** — FastAPI + SQLAlchemy 2.0 async sessions + asyncpg driver.
No blocking I/O in the request path.

**Test strategy** — integration tests are the primary layer (real Postgres,
FastAPI TestClient, `task_always_eager=True` for Celery, `MockLLMProvider`
via `dependency_overrides`). Every tenant-scoped repo method has a
corresponding org isolation test.

---

## Documentation

| Doc | Contents |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, SOLID principles, layer responsibilities |
| [docs/ENTITIES.md](docs/ENTITIES.md) | All domain entities, fields, business rules |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema design, migrations, multi-tenancy at DB level |
| [docs/MULTITENANCY.md](docs/MULTITENANCY.md) | Tenant isolation strategy and enforcement points |
| [docs/API.md](docs/API.md) | REST API reference — all endpoints, request/response shapes |
| [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md) | LLMProvider ABC, HuggingFace and Mock implementations |
| [docs/SOURCES.md](docs/SOURCES.md) | SourceProvider ABC, CSV and simulated source implementations |
| [docs/WORKERS.md](docs/WORKERS.md) | Celery configuration, task lifecycle, error handling |
| [docs/TESTING.md](docs/TESTING.md) | Test pyramid, fixtures, patterns, how to write tests |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local setup, hot reload, migrations, common issues |

---

## API Overview

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
GET    /api/v1/auth/me

GET    /api/v1/organizations/me

POST   /api/v1/sources
GET    /api/v1/sources
GET    /api/v1/sources/{id}
PATCH  /api/v1/sources/{id}
DELETE /api/v1/sources/{id}

POST   /api/v1/sources/{id}/ingest
GET    /api/v1/reviews

POST   /api/v1/jobs
GET    /api/v1/jobs
GET    /api/v1/jobs/{id}

GET    /api/v1/summaries
GET    /api/v1/summaries/{id}
```

Full request/response documentation: [docs/API.md](docs/API.md)
