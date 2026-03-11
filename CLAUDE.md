# CLAUDE.md — SentimentPulse

Instructions for Claude Code working in this repository.
Read this file before making any changes.

---

## Project Overview

SentimentPulse is a multi-tenant customer feedback aggregator.
See `README.md` for what it does and `docs/ARCHITECTURE.md` for how it is designed.

---

## Non-Negotiable Rules

1. **No auto-commits.** Never commit or push without explicit user instruction.
2. **No auto-changes.** Propose changes and wait for approval before writing code.
3. **Docs-first.** If a task requires a new module or significant design decision,
   update or create the relevant doc before writing implementation code.
4. **Keep `memory/PROGRESS.md` updated.** Mark steps `[x]` when complete and
   update the "Last updated" line after every step.
5. **No speculative additions.** YAGNI strictly enforced — only build what is
   asked for right now.

---

## Code Quality Standards

### Python (backend)

- Follow SOLID, DRY, YAGNI
- Max file length: no hard limit, but prefer splitting over long files
- All services depend on abstractions (ABCs), never on concrete implementations
- No business logic in routers or repositories — routers call services, services call repos
- `organization_id` is required on every repo method that touches tenant data — never optional
- Use `async`/`await` throughout — no synchronous DB or I/O calls in the request path
- Pydantic schemas for all request bodies and response shapes — no raw dicts crossing layer boundaries

### React / TypeScript (frontend)

- Hard limit: **100 lines per component or hook file**
- Zustand owns: JWT token, current user, org_id
- TanStack Query owns: all server data (reviews, jobs, summaries, sources)
- One API file per domain: `api/auth.ts`, `api/reviews.ts`, etc.
- No business logic in components — components render, hooks fetch, api files call the server

---

## Architecture Constraints

- **Layer order:** Router → Service → Repository → DB. Never skip a layer.
- **Provider injection:** `LLMProvider` and `SourceProvider` are always injected — never
  imported directly into services.
- **Tenant isolation:** enforced at the repository layer. The service passes `organization_id`
  down; the repo always filters by it.
- **JWT org_id:** extracted in `api/deps.py` — not re-fetched from DB on every request.
- **Celery tasks** call services — they are not a separate architecture layer.

---

## Important Files

| File | Purpose |
|------|---------|
| `docs/ENTITIES.md` | Source of truth for all entity fields and business rules |
| `docs/ARCHITECTURE.md` | Layering, SOLID application, design decisions |
| `docs/API.md` | All endpoint contracts — match these exactly when implementing |
| `docs/TESTING.md` | Fixture design, test patterns, writing rules |
| `docs/DEVELOPMENT.md` | Local setup, migration commands, running tests |
| `backend/app/core/config.py` | All settings via pydantic-settings — add new env vars here |
| `backend/app/api/deps.py` | Composition root — concrete providers wired here |
| `backend/tests/conftest.py` | All shared test fixtures |
| `memory/PROGRESS.md` | Phase-by-phase tracker — keep this updated |

---

## Testing Rules

- Every new repo method that returns tenant data **must** have an org isolation test in
  `tests/integration/test_org_isolation.py`
- Integration tests use real Postgres (`TEST_DATABASE_URL`), `MockLLMProvider` via
  `dependency_overrides`, and `task_always_eager=True`
- Unit tests use injected mocks — no DB, no HTTP
- One assertion focus per test — name tests descriptively:
  `test_login_returns_access_token`, not `test_login`
- See `docs/TESTING.md` for full rules

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Python modules | snake_case | `review_service.py` |
| Python classes | PascalCase | `ReviewService` |
| React components | PascalCase | `ReviewTable.tsx` |
| React hooks | camelCase with `use` prefix | `useJobPolling.ts` |
| TypeScript types | PascalCase | `SummarizationJob` |
| API routes | kebab-case | `/api/v1/batch-jobs` |
| Env variables | UPPER_SNAKE_CASE | `HUGGINGFACE_API_KEY` |
| Test functions | `test_<what>_<expected>` | `test_login_returns_access_token` |

---

## Common Gotchas

- `DATABASE_URL` uses `postgresql+asyncpg://` — not `postgresql://`
- `TEST_DATABASE_URL` must point to a **separate** database, not the dev database
- When running the backend outside Docker, update `.env` to use `localhost` instead
  of Docker service names (`db`, `redis`)
- Alembic autogenerate is a starting point — always review generated migration files
  before applying
- `organization_id` comes from the JWT token, not from request parameters
- `MockLLMProvider` returns deterministic output — test assertions should use its
  known fixed values, not dynamic ones

---

## Phase Reference

Current phase tracker: `memory/PROGRESS.md`

Phases at a glance:
- **Phase 1** — Foundation: Docker, FastAPI, DB models, auth, test scaffold
- **Phase 2** — Multi-tenancy: org isolation enforcement and tests
- **Phase 3** — Review Ingestion: CSV upload, source CRUD, review repo/service
- **Phase 4** — LLM + Workers: provider ABC, Celery task, job/summary APIs
- **Phase 5** — Frontend: Vite scaffold, Zustand, TanStack Query, job polling UI
- **Phase 6** — Simulated Sources: AppStore, Google, Twitter providers
- **Phase 7** — E2E Tests + Final Polish: Playwright, audit pass, docs finalized
