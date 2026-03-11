# Testing — SentimentPulse

This document describes the testing strategy, test categories, fixture design,
and patterns used across the project. Read this before writing any tests.

---

## Test Pyramid

```
        ┌──────────────┐
        │   E2E Tests  │   Playwright — Phase 5+
        │  (few, slow) │   Full browser, real stack
        ├──────────────┤
        │  Unit Tests  │   pytest — services, repos, utils
        │   (medium)   │   No DB, no HTTP — injected mocks only
        ├──────────────┤
        │ Integration  │   pytest + FastAPI TestClient + test Postgres
        │  (primary)   │   HTTP in → DB out — real behaviour verified
        └──────────────┘
```

**Integration tests are the primary layer.** They exercise the full request
path (router → service → repo → DB) using a real Postgres database, giving high
confidence with minimal mocking.

Unit tests focus on isolated logic: service rules, repository query logic, and
utility functions — with repositories and providers replaced by mocks.

E2E tests run against the full running stack in Phase 5+. They cover the
critical user journeys end-to-end through a real browser.

---

## Test Database

A separate Postgres database is used for all tests. It is configured via an
environment variable, keeping it completely isolated from the development
database.

```
TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse_test
```

### Transaction rollback strategy

Each integration test runs inside a database transaction that is **rolled back**
at the end of the test. This means:

- No data persists between tests
- No `DELETE` or `TRUNCATE` needed between tests
- Tests are fast — rollback is cheaper than truncation
- Tests are isolated — one test's writes never affect another

This is implemented in `conftest.py` using SQLAlchemy's `begin_nested()` and
a custom `test_db` fixture that wraps each test in a savepoint.

---

## Celery in Tests

Celery tasks are configured with `task_always_eager = True` in the test
settings. This runs tasks **synchronously in the same process** when `.delay()`
or `.apply_async()` is called — no broker, no worker process, no Redis needed.

```python
# In test settings
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True  # surface exceptions immediately
```

This means the full job flow (trigger → task runs → DB updated) can be tested
as a single synchronous call in integration tests.

---

## LLM Provider in Tests

`MockLLMProvider` is always injected in tests via FastAPI's dependency override
mechanism. No HuggingFace API key or network call is ever made during a test run.

```python
# In conftest.py
@pytest.fixture
def mock_llm_provider():
    return MockLLMProvider()

# Injected into the app client fixture
app.dependency_overrides[get_llm_provider] = lambda: mock_llm_provider()
```

`MockLLMProvider` returns a deterministic `SummaryResult` with hardcoded pain
points and a fixed sentiment score. Tests can assert against these known values.

---

## Fixtures — `conftest.py`

All shared fixtures live in `backend/tests/conftest.py`. Each fixture is
scoped appropriately to keep tests fast without repeating expensive setup.

### `test_db` — `scope="function"`

Creates a database connection, begins a transaction, yields the session to the
test, then rolls back. This is the core isolation mechanism.

```python
@pytest_asyncio.fixture
async def test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(conn) as session:
            async with session.begin_nested():
                yield session
            await session.rollback()
```

### `client` — `scope="function"`

Builds a `TestClient` (or `AsyncClient`) wrapping the FastAPI app, with:
- `get_db` overridden to use `test_db` session
- `get_llm_provider` overridden to use `MockLLMProvider`

```python
@pytest_asyncio.fixture
async def client(test_db, mock_llm_provider):
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_llm_provider] = lambda: mock_llm_provider
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

### `auth_headers` — `scope="function"`

Registers a test user, logs in, and returns the `Authorization: Bearer <token>`
header dictionary. Used by any test that requires authentication.

```python
@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/api/v1/auth/register", json={...})
    resp = await client.post("/api/v1/auth/login", json={...})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

### `org_factory` — `scope="function"`

Creates one or more organizations directly in the test DB. Used in multi-tenancy
isolation tests that need two separate orgs to verify cross-org data leakage.

```python
@pytest_asyncio.fixture
async def org_factory(test_db):
    async def _create(name: str) -> Organization:
        org = Organization(name=name)
        test_db.add(org)
        await test_db.flush()
        return org
    return _create
```

### `mock_llm_provider` — `scope="session"`

Returns a single `MockLLMProvider` instance shared across the test session.
Stateless, so session scope is safe and avoids repeated construction.

---

## Test File Structure

```
backend/tests/
├── conftest.py                        ← shared fixtures (above)
├── unit/
│   ├── services/
│   │   ├── test_auth_service.py       ← auth logic: hashing, token generation
│   │   ├── test_job_service.py        ← job lifecycle rules
│   │   └── test_summary_service.py    ← MockLLMProvider injected, no DB
│   ├── repositories/
│   │   └── test_review_repo.py        ← repo logic with mock session
│   └── utils/
│       └── test_security.py           ← JWT encode/decode, password hashing
└── integration/
    ├── test_auth_flow.py              ← register → login → refresh → me
    ├── test_org_isolation.py          ← Org A cannot read Org B's data
    ├── test_review_ingestion.py       ← CSV upload → reviews in DB
    ├── test_job_creation.py           ← POST /jobs → status=pending
    ├── test_worker_processing.py      ← task_always_eager + MockLLM → completed
    └── test_job_polling.py            ← GET /jobs/{id} status transitions
```

---

## What Each Category Covers

### Unit — `tests/unit/`

- **No database.** Repositories are replaced by mock objects.
- **No HTTP.** Services are called directly, not via the API.
- **Fast.** Each test runs in milliseconds.
- Covers: business rules, conditional logic, error paths, pure functions.

```python
# Example: test that job_service raises when job not found
async def test_get_job_raises_not_found(mock_job_repo):
    mock_job_repo.get.return_value = None
    service = JobService(job_repo=mock_job_repo, ...)
    with pytest.raises(JobNotFoundError):
        await service.get_job(job_id=uuid4(), organization_id=uuid4())
```

### Integration — `tests/integration/`

- **Real Postgres DB** (test database, rolled back after each test).
- **Full HTTP path** via `AsyncClient` wrapping the FastAPI app.
- **No real Celery broker** — `task_always_eager=True`.
- **No real LLM** — `MockLLMProvider` injected via `dependency_overrides`.
- Covers: request validation, auth enforcement, DB writes, org isolation.

```python
# Example: unauthenticated request returns 401
async def test_get_reviews_requires_auth(client):
    resp = await client.get("/api/v1/reviews")
    assert resp.status_code == 401
```

```python
# Example: org isolation — Org B user cannot see Org A's reviews
async def test_org_b_cannot_read_org_a_reviews(client, org_factory, ...):
    ...
    resp = await client_b.get(f"/api/v1/reviews?source_id={source_a_id}")
    assert resp.status_code == 404  # or empty list — never Org A's data
```

### E2E — `tests/e2e/` (Phase 5+)

- **Playwright** drives a real browser against the full running Docker stack.
- **No mocks.** Uses the same MockLLMProvider but via the real running backend.
- Slow — run in CI only, not on every local change.
- Covers: login flow, CSV upload, job trigger, polling, summary display.

---

## Running Tests

```bash
# Run all tests
pytest

# Run only integration tests
pytest tests/integration/

# Run only unit tests
pytest tests/unit/

# Run a single file
pytest tests/integration/test_auth_flow.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

### Environment setup for tests

```bash
# Required: test database URL
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse_test

# Optional: suppress HuggingFace API key (MockProvider used automatically)
unset HUGGINGFACE_API_KEY
```

---

## Test Writing Rules

1. **One assertion focus per test.** Each test should verify one specific
   behaviour. Name the test to describe that behaviour: `test_login_returns_access_token`,
   not `test_login`.

2. **Arrange / Act / Assert.** Structure every test in three clear sections.
   Separate them with blank lines. Do not interleave setup with assertions.

3. **Never share state between tests.** Each test must be independent. Do not
   rely on the order tests run. The transaction rollback fixture enforces this
   for DB state, but be vigilant with any other shared mutable state.

4. **Test the behaviour, not the implementation.** Assert on HTTP status codes,
   response bodies, and DB records — not on internal method call counts unless
   there is a specific reason.

5. **Keep unit tests fast.** If a unit test touches the DB or network, it is
   an integration test. Move it.

6. **Multi-tenancy must always be tested.** Every new repo method that returns
   tenant data must have a corresponding isolation test in
   `test_org_isolation.py` that proves Org B cannot see Org A's records.

---

## pytest Configuration

```ini
# pytest.ini (or [tool.pytest.ini_options] in pyproject.toml)
[pytest]
asyncio_mode = auto
testpaths = tests
env =
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse_test
    CELERY_TASK_ALWAYS_EAGER=true
```

`asyncio_mode = auto` means all `async def test_*` functions are automatically
treated as async tests — no `@pytest.mark.asyncio` decorator needed.

---

See `docs/ARCHITECTURE.md` for how the test strategy fits the overall design.
See `docs/WORKERS.md` for Celery configuration details.
