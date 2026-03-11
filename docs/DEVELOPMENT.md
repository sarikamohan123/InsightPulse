# Development Guide — SentimentPulse

This document covers local environment setup, running the stack, and
day-to-day development workflows. Read this before writing any code.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker Desktop | 4.x+ | Runs Postgres, Redis, backend, worker, frontend |
| Python | 3.12 | Backend development outside Docker |
| Node.js | 20 LTS | Frontend development outside Docker |
| Git | any | Version control |

All services run in Docker. Python and Node.js are only needed if you
want to run services directly on the host (faster iteration, easier debugging).

---

## Repository Structure

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
│   │   ├── repositories/  ← data access layer
│   │   ├── providers/
│   │   │   ├── llm/       ← LLMProvider ABC + implementations
│   │   │   └── sources/   ← SourceProvider ABC + implementations
│   │   ├── workers/       ← Celery app + tasks
│   │   └── main.py        ← FastAPI app factory
│   ├── tests/             ← pytest test suite
│   ├── alembic/           ← database migrations
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/           ← Axios functions (one file per domain)
│   │   ├── hooks/         ← TanStack Query wrappers
│   │   ├── store/         ← Zustand stores
│   │   ├── components/    ← reusable UI components
│   │   ├── pages/         ← route-level page components
│   │   └── types/         ← TypeScript interfaces
│   ├── tests/e2e/         ← Playwright tests
│   ├── package.json
│   └── Dockerfile
├── docs/                  ← all architecture and design docs
├── docker-compose.yml
├── docker-compose.override.yml
└── README.md
```

---

## First-Time Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd InsightPulse
```

### 2. Create the backend environment file

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in required values:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@db:5432/sentimentpulse
TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse_test

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
JWT_SECRET_KEY=change-this-to-a-random-secret-at-least-32-chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# LLM (optional — MockProvider is used automatically if absent)
HUGGINGFACE_API_KEY=

# App
APP_ENV=development
```

`HUGGINGFACE_API_KEY` is optional. If left blank, `MockLLMProvider` is used
automatically for all LLM calls. The full job flow works without an API key.

### 3. Start the full stack

```bash
docker compose up --build
```

This starts:
- `db` — PostgreSQL 16 on port `5432`
- `redis` — Redis 7 on port `6379`
- `backend` — FastAPI on port `8000`
- `worker` — Celery worker (same image as backend)
- `frontend` — Vite dev server on port `5173`

### 4. Run database migrations

On first run, apply all Alembic migrations:

```bash
docker compose exec backend alembic upgrade head
```

On subsequent runs, migrations are applied automatically on container start
(the `backend` entrypoint runs `alembic upgrade head` before starting uvicorn).

### 5. Verify the stack is running

```
API docs:   http://localhost:8000/docs
Frontend:   http://localhost:5173
API health: http://localhost:8000/health
```

---

## Daily Workflow

### Start the stack

```bash
docker compose up
```

### Stop the stack

```bash
docker compose down
```

To also delete the database volume (full reset):

```bash
docker compose down -v
```

### View logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f backend
docker compose logs -f worker
```

### Rebuild after dependency changes

If you add packages to `requirements.txt` or `package.json`:

```bash
docker compose up --build
```

---

## Hot Reload

`docker-compose.override.yml` mounts source directories as volumes so that
code changes on the host are reflected immediately without rebuilding.

- **Backend** — uvicorn runs with `--reload`. Edit any `.py` file and the
  server restarts automatically.
- **Frontend** — Vite's HMR (Hot Module Replacement) updates the browser
  instantly on `.tsx`/`.ts`/`.css` changes.
- **Worker** — Celery runs with `--autoreload` (watchdog). Task code changes
  are picked up without restarting the container.

---

## Running the Backend Locally (without Docker)

Useful for faster iteration and easier debugger attachment.

### Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Start dependencies via Docker

```bash
# Start only Postgres and Redis (not the backend or worker)
docker compose up db redis
```

### Run the API server

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run the Celery worker

```bash
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

Update `backend/.env` to use `localhost` instead of Docker service names:

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse
REDIS_URL=redis://localhost:6379/0
```

---

## Running the Frontend Locally (without Docker)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server starts on `http://localhost:5173` and proxies `/api`
requests to `http://localhost:8000`.

---

## Database Migrations

### Create a new migration

After modifying any SQLAlchemy model:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `backend/alembic/versions/` before applying it.
Autogenerate is a starting point — always verify the output.

### Apply migrations

```bash
docker compose exec backend alembic upgrade head
```

### Roll back the last migration

```bash
docker compose exec backend alembic downgrade -1
```

### View migration history

```bash
docker compose exec backend alembic history --verbose
```

---

## Running Tests

Tests require the test database to exist. Create it once:

```bash
# Connect to Postgres and create the test DB
docker compose exec db psql -U postgres -c "CREATE DATABASE sentimentpulse_test;"
```

### Run all tests

```bash
docker compose exec backend pytest
```

### Run tests locally (outside Docker)

```bash
cd backend
source .venv/bin/activate
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sentimentpulse_test
pytest
```

### Run with coverage

```bash
pytest --cov=app --cov-report=term-missing
```

See `docs/TESTING.md` for full test strategy, fixture documentation, and
test writing rules.

---

## Accessing the API Docs

FastAPI generates interactive API documentation automatically:

- **Swagger UI** — `http://localhost:8000/docs` — try endpoints directly
- **ReDoc** — `http://localhost:8000/redoc` — cleaner read-only reference

Both are available in development and are disabled in production
(`APP_ENV=production` disables the docs endpoints).

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | yes | — | Async Postgres URL for the app |
| `TEST_DATABASE_URL` | tests only | — | Separate DB for test runs |
| `REDIS_URL` | yes | — | Redis URL for Celery broker + results |
| `JWT_SECRET_KEY` | yes | — | Secret for signing JWT tokens |
| `JWT_ALGORITHM` | no | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | no | `7` | Refresh token lifetime |
| `HUGGINGFACE_API_KEY` | no | — | If absent, MockLLMProvider is used |
| `APP_ENV` | no | `development` | `development` or `production` |

---

## Common Issues

### Port already in use

If port `5432`, `6379`, `8000`, or `5173` is in use by another process:

```bash
# Find what is using the port (example: 5432)
lsof -i :5432

# Or change the host port in docker-compose.override.yml
```

### Alembic "Target database is not up to date"

```bash
docker compose exec backend alembic upgrade head
```

### Database connection refused (running locally)

Ensure Docker Compose services `db` and `redis` are running:

```bash
docker compose up db redis
```

And confirm `backend/.env` uses `localhost` (not `db`) for the database host
when running the backend outside Docker.

### Celery tasks not executing

Verify `REDIS_URL` is correct and Redis is reachable. In tests, confirm
`CELERY_TASK_ALWAYS_EAGER=true` is set so tasks run synchronously without
a broker.

---

See `docs/ARCHITECTURE.md` for system design.
See `docs/TESTING.md` for the test strategy.
