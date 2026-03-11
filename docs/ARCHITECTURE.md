# Architecture — SentimentPulse

This document describes the system architecture, design decisions, and principles
that govern how SentimentPulse is structured. Read this before contributing.

---

## System Overview

SentimentPulse is a multi-tenant customer feedback aggregator. It ingests reviews
from multiple sources, processes them in background jobs using an LLM, and presents
structured summaries (top pain points) through a dashboard UI.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React)                          │
│   Zustand (auth/session)  +  TanStack Query (server state)      │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTPS / JSON
┌───────────────────────────────▼─────────────────────────────────┐
│                     FastAPI (Python)                            │
│   Routers → Deps → Services → Repositories → SQLAlchemy        │
└──────────┬──────────────────────────────────────┬──────────────┘
           │ Celery task dispatch                  │ SQL (async)
┌──────────▼──────────┐               ┌────────────▼─────────────┐
│   Redis             │               │   PostgreSQL 16           │
│   Broker + Results  │               │   Row-level multi-tenancy │
└──────────┬──────────┘               └──────────────────────────┘
           │
┌──────────▼──────────┐
│   Celery Worker     │
│   summarization     │
│   ingestion         │
└──────────┬──────────┘
           │ HTTP
┌──────────▼──────────┐
│   LLM Provider      │
│   HuggingFace API   │
│   (or MockProvider) │
└─────────────────────┘
```

---

## Layered Architecture

Each layer has a single, well-defined responsibility.
Layers only communicate downward — never skip a layer.

```
┌─────────────────────────────────┐
│  API Layer (Routers + Deps)     │  HTTP in/out, auth, request validation
├─────────────────────────────────┤
│  Service Layer                  │  Business logic, orchestration
├─────────────────────────────────┤
│  Repository Layer               │  Data access only, org_id enforced here
├─────────────────────────────────┤
│  Model Layer (SQLAlchemy)       │  ORM table definitions, no logic
├─────────────────────────────────┤
│  Database (PostgreSQL)          │  Persistence
└─────────────────────────────────┘

Provider Layer (LLM + Sources) sits alongside Services.
Workers (Celery) call Services — they are not a separate layer.
```

### Why this layering?

**API layer** knows nothing about the database. It validates input, checks auth,
and calls a service. If we swap FastAPI for a CLI or a gRPC server, services
are untouched.

**Service layer** contains all business decisions. It knows what a
SummarizationJob is and what rules govern it. It does not know what SQL looks like.

**Repository layer** knows SQL. It does not know business rules. Injecting
repos into services (via constructor) means services can be unit-tested with
a mock repository — no database required.

**Provider layer** sits alongside services and is always injected as an
abstraction. The service never imports `HuggingFaceLLMProvider` directly.

---

## SOLID Principles — Applied

### S — Single Responsibility

| Component | Its one responsibility |
|-----------|----------------------|
| `api/v1/auth.py` | Handle auth HTTP requests — nothing else |
| `services/job_service.py` | Job lifecycle business logic |
| `repositories/review_repo.py` | Review data access with org isolation |
| `workers/tasks/summarization.py` | Execute the async LLM summarization task |
| `providers/llm/huggingface.py` | Call the HuggingFace API |

If you find yourself writing "and also" when describing what a class does,
it has more than one responsibility.

### O — Open/Closed

`LLMProvider` and `SourceProvider` are abstract base classes.
Adding a new LLM (e.g. Gemini) or a new source (e.g. Slack) requires:
- Creating a new file that implements the ABC
- Registering it in the provider factory

No existing code is modified. The system is open for extension, closed for modification.

### L — Liskov Substitution

`MockLLMProvider` and `HuggingFaceLLMProvider` are interchangeable.
Any code that accepts `LLMProvider` works identically with either.
This is what makes testing without API keys possible.

Same applies to all `SourceProvider` implementations.

### I — Interface Segregation

`LLMProvider` exposes exactly one method:
```python
async def summarize(self, reviews: list[str]) -> SummaryResult: ...
```

`SourceProvider` exposes exactly two:
```python
async def fetch_reviews(self) -> list[ReviewData]: ...
@property
def source_type(self) -> SourceType: ...
```

Implementations are never forced to carry methods they do not use.

### D — Dependency Inversion

Services depend on abstractions, not concrete classes:

```python
# Good — depends on the ABC
class JobService:
    def __init__(self, llm_provider: LLMProvider, job_repo: JobRepository): ...

# Bad — depends on a concrete class
class JobService:
    def __init__(self):
        self.llm = HuggingFaceLLMProvider()  # untestable, hardcoded
```

FastAPI's `Depends()` is the injection mechanism. Concrete providers are
wired at the composition root (`api/deps.py`), not inside services.

---

## Multi-tenancy Design

Every tenant-owned table carries `organization_id`.
Isolation is enforced at the **repository layer**.

```python
# Every repo method that touches tenant data requires org_id
async def get_reviews(
    self,
    organization_id: UUID,   # required — never optional
    source_id: UUID,
    session: AsyncSession,
) -> list[Review]: ...
```

The `organization_id` is extracted from the JWT token in `api/deps.py`
and passed through the service into the repository on every call.

**No service or API handler may call a repo method without supplying `organization_id`.**

See `docs/MULTITENANCY.md` for full detail.

---

## Authentication Flow

```
POST /auth/register → creates User + Organization (or joins existing org)
POST /auth/login    → returns access_token (15min) + refresh_token (7d)
POST /auth/refresh  → returns new access_token using refresh_token
```

- Access tokens are short-lived (15 minutes) — limits exposure if leaked
- Refresh tokens are stored hashed in the database — can be revoked server-side
- All protected routes require `Authorization: Bearer <access_token>`
- `organization_id` is embedded in the JWT payload — no extra DB lookup per request

---

## Background Job Flow

```
1. User clicks "Run Summarization" in UI
2. POST /jobs  →  JobService.create_job()
3. Job record inserted with status=pending, filters saved
4. Celery task dispatched with job_id
5. Worker picks up task:
   a. Updates job status → running
   b. Queries reviews using stored filters
   c. Calls LLMProvider.summarize(reviews)
   d. Writes Summary record
   e. Updates job status → completed (or failed + error_message)
6. Frontend polls GET /jobs/{id} via TanStack Query
7. On completed: fetches Summary and displays pain points
```

Redis serves as both the Celery **broker** (receives tasks) and
**result backend** (stores task outcomes). One service, two roles.

Celery is configured with `task_always_eager=True` in the test environment,
which runs tasks synchronously without a broker — no Redis required in tests.

---

## LLM Provider Abstraction

```
providers/llm/
├── base.py           ← LLMProvider ABC + SummaryResult dataclass
├── huggingface.py    ← calls HuggingFace Inference API
└── mock.py           ← returns deterministic fake output (dev + tests)
```

The active provider is selected in `api/deps.py` based on config:

```python
def get_llm_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    if settings.huggingface_api_key:
        return HuggingFaceLLMProvider(api_key=settings.huggingface_api_key)
    return MockLLMProvider()
```

This means: **no API key configured = mock provider used automatically**.
Developers can build and test the full job flow without a HuggingFace account.

See `docs/LLM_PROVIDERS.md` for full detail.

---

## Source Provider Abstraction

```
providers/sources/
├── base.py               ← SourceProvider ABC + ReviewData dataclass
├── csv_provider.py       ← parses uploaded CSV files
├── appstore_provider.py  ← simulates App Store reviews
├── google_provider.py    ← simulates Google/Yelp-style reviews
└── twitter_provider.py   ← simulates social mentions
```

All providers return the same `ReviewData` shape regardless of source.
Adding a real connector (e.g. actual App Store API) means implementing
`SourceProvider` in a new file — nothing else changes.

See `docs/SOURCES.md` for field mapping and simulation strategy.

---

## Frontend Architecture

```
src/
├── store/authStore.ts     ← Zustand: JWT token, decoded user, org_id
├── api/client.ts          ← Axios instance with JWT interceptors + auto-refresh
├── api/*.ts               ← one file per domain (plain async functions)
├── hooks/use*.ts          ← TanStack Query wrappers (< 100 lines each)
├── components/            ← pure UI components (< 100 lines each)
├── pages/                 ← route-level containers (compose components + hooks)
└── types/                 ← TypeScript interfaces matching backend schemas
```

**State split:**
- Zustand owns: JWT token, current user identity, current org_id
- TanStack Query owns: all server data (reviews, jobs, summaries, sources)

**Polling strategy for job status:**
TanStack Query's `refetchInterval` polls `GET /jobs/{id}` every 3 seconds
while `status === "pending" | "running"`. Polling stops automatically when
`status === "completed" | "failed"`.

See `docs/FRONTEND.md` for component structure and hook patterns.

---

## Testing Strategy

```
Integration tests (primary)   pytest + FastAPI TestClient + test Postgres DB
Unit tests                    pytest with injected mocks (no DB, no HTTP)
E2E tests (Phase 5+)          Playwright against running local stack
```

Key enablers:
- `TEST_DATABASE_URL` env var swaps the database for tests
- `app.dependency_overrides` injects `MockLLMProvider` in all tests
- `task_always_eager=True` runs Celery tasks synchronously (no broker needed)
- Repository constructor injection allows unit tests with mock repos

See `docs/TESTING.md` for fixture design and test patterns.

---

## Tech Stack Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Web framework | FastAPI | Async, auto-docs, clean DI via Depends() |
| ORM | SQLAlchemy 2.0 async | Production standard, repository pattern fits cleanly |
| Task queue | Celery + Redis | Industry standard, wide adoption, strong retry support |
| Multi-tenancy | Row-level (org_id) | Simpler than schema-per-tenant, realistic for interviews |
| LLM abstraction | Provider ABC | Swap real/mock without changing service code |
| Auth | JWT (access + refresh) | Stateless access tokens, revocable refresh tokens |
| Frontend state | Zustand + TanStack Query | Zustand for auth session, TanStack Query for server data |
| Containerization | Docker Compose | One command to run full stack locally |

---

## File Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Python modules | snake_case | `review_service.py` |
| Python classes | PascalCase | `ReviewService` |
| React components | PascalCase | `ReviewTable.tsx` |
| React hooks | camelCase with `use` prefix | `useJobPolling.ts` |
| TypeScript types | PascalCase | `SummarizationJob` |
| API routes | kebab-case | `/api/v1/batch-jobs` |
| Env variables | UPPER_SNAKE_CASE | `HUGGINGFACE_API_KEY` |
