# Database Design — SentimentPulse

This document covers the full PostgreSQL schema, column types, indexes,
constraints, migration strategy, and design decisions.
It derives directly from `docs/ENTITIES.md` — if an entity changes, update both.

---

## Design Principles

1. **Every tenant-owned table carries `organization_id`** — no exceptions.
   This is the row-level multi-tenancy guarantee.

2. **UUIDs as primary keys** — not auto-incrementing integers.
   UUIDs are safe to generate client-side, do not leak record counts,
   and work across distributed systems without collision.

3. **Soft deletes via `is_active`** — we never hard-delete records that
   have dependents. This preserves referential integrity and audit history.

4. **JSONB for flexible metadata** — used for `config`, `filters`,
   `raw_metadata`, and `pain_points`. Postgres JSONB is indexed and queryable.

5. **Timestamps on every table** — `created_at` is auto-set on insert.
   `updated_at` is auto-set on update via SQLAlchemy event or DB trigger.

---

## Entity Relationship Diagram

```
organizations
  │
  ├──< users
  │
  ├──< review_sources
  │       │
  │       └──< reviews
  │
  ├──< summarization_jobs
  │       │
  │       └──── summaries (1:1)
  │
  └── (organization_id on all tables above)

users
  └──< refresh_tokens
```

Crow's foot notation: `──<` = one-to-many, `────` = one-to-one

---

## Table Definitions

### `organizations`

```sql
CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255)    NOT NULL,
    slug        VARCHAR(100)    NOT NULL UNIQUE,
    plan        VARCHAR(20)     NOT NULL DEFAULT 'free',
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_plan CHECK (plan IN ('free', 'pro', 'enterprise'))
);
```

**Why `slug`?** URL-safe identifier for the org (e.g. `/org/acme-corp`).
Unique constraint ensures no two orgs share a slug.

**Why `TIMESTAMPTZ`?** Stores timestamps with timezone — avoids daylight
saving bugs when the server timezone differs from the user's timezone.

---

### `users`

```sql
CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID            NOT NULL REFERENCES organizations(id),
    email            VARCHAR(255)    NOT NULL UNIQUE,
    hashed_password  VARCHAR(255)    NOT NULL,
    role             VARCHAR(20)     NOT NULL DEFAULT 'member',
    is_active        BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_role CHECK (role IN ('admin', 'member'))
);

CREATE INDEX idx_users_organization_id ON users(organization_id);
CREATE INDEX idx_users_email ON users(email);
```

**Why `email` unique globally?** A user's email is their identity across the
system. Per-org uniqueness would allow the same email in two orgs, which breaks
password reset and causes auth ambiguity.

**Why index on `organization_id`?** Most user queries filter by org.
Without this index, every user lookup would be a full table scan.

---

### `refresh_tokens`

```sql
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(255)    NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ     NOT NULL,
    revoked     BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
```

**Why store the hash, not the token?** If the database is breached, hashed
tokens cannot be replayed. The same reason we hash passwords.

**Why `ON DELETE CASCADE`?** If a user is deleted, their refresh tokens
should be deleted automatically — no orphaned auth records.

**Why `revoked` flag?** Allows server-side logout. When a user logs out,
we set `revoked = TRUE`. The token is then rejected even if not yet expired.

---

### `review_sources`

```sql
CREATE TABLE review_sources (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID            NOT NULL REFERENCES organizations(id),
    name             VARCHAR(255)    NOT NULL,
    source_type      VARCHAR(20)     NOT NULL,
    config           JSONB,
    is_active        BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_source_type
        CHECK (source_type IN ('csv', 'appstore', 'google', 'twitter'))
);

CREATE INDEX idx_review_sources_organization_id ON review_sources(organization_id);
CREATE INDEX idx_review_sources_type ON review_sources(organization_id, source_type);
```

**Why composite index on `(organization_id, source_type)`?**
The dashboard will frequently query "all CSV sources for org X" — a composite
index makes this fast without scanning the full table.

**Why `config` is nullable JSONB?** CSV sources need no persistent config
(the file is uploaded per-ingestion). Other types store their connection
parameters here. Nullable avoids storing empty objects.

---

### `reviews`

```sql
CREATE TABLE reviews (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID            NOT NULL REFERENCES organizations(id),
    source_id        UUID            NOT NULL REFERENCES review_sources(id),
    external_id      VARCHAR(255),
    content          TEXT            NOT NULL,
    author           VARCHAR(255),
    rating           NUMERIC(3, 1),
    review_date      DATE,
    raw_metadata     JSONB,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_rating CHECK (rating >= 0 AND rating <= 5),
    CONSTRAINT uq_review_external
        UNIQUE (source_id, external_id)
);

CREATE INDEX idx_reviews_organization_id ON reviews(organization_id);
CREATE INDEX idx_reviews_source_id ON reviews(organization_id, source_id);
CREATE INDEX idx_reviews_review_date ON reviews(organization_id, review_date DESC);
CREATE INDEX idx_reviews_rating ON reviews(organization_id, rating);
```

**Why `NUMERIC(3,1)` for rating?** Stores values like `4.5` exactly.
`FLOAT` has precision errors — `4.5` might be stored as `4.4999...`.

**Why the unique constraint on `(source_id, external_id)`?**
Prevents duplicate ingestion. If a CSV is uploaded twice or an API is
polled repeatedly, the same review won't appear twice.

**Why index on `review_date DESC`?** Most dashboard queries sort by
most recent first. A descending index means Postgres doesn't need to
sort the result — it reads in index order.

**Why index on `rating`?** `SummarizationJob.filters` can include
`rating_max`. Filtering low-rated reviews is the primary use case.

---

### `summarization_jobs`

```sql
CREATE TABLE summarization_jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID            NOT NULL REFERENCES organizations(id),
    source_id        UUID            NOT NULL REFERENCES review_sources(id),
    status           VARCHAR(20)     NOT NULL DEFAULT 'pending',
    review_count     INTEGER         NOT NULL,
    filters          JSONB           NOT NULL,
    celery_task_id   VARCHAR(255),
    error_message    TEXT,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_job_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    CONSTRAINT chk_review_count
        CHECK (review_count > 0)
);

CREATE INDEX idx_jobs_organization_id ON summarization_jobs(organization_id);
CREATE INDEX idx_jobs_source_id ON summarization_jobs(organization_id, source_id);
CREATE INDEX idx_jobs_status ON summarization_jobs(organization_id, status);
CREATE INDEX idx_jobs_celery_task_id ON summarization_jobs(celery_task_id)
    WHERE celery_task_id IS NOT NULL;
```

**Why partial index on `celery_task_id`?** The worker looks up jobs by
Celery task ID when reporting completion. The `WHERE NOT NULL` condition
makes this index smaller and faster — only active jobs have a task ID.

**Why `filters JSONB NOT NULL`?** Batch selection criteria must always
be recorded. A job without filters is unauditable. See `ENTITIES.md`
for the exact filters structure.

**Why no unique constraint on "one active job per source"?**
This rule is enforced at the service layer, not the DB constraint.
A DB constraint would require a partial unique index on a non-boolean
status, which is harder to manage across migrations. Service-layer
enforcement is simpler and equally reliable.

---

### `summaries`

```sql
CREATE TABLE summaries (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID            NOT NULL REFERENCES organizations(id),
    job_id           UUID            NOT NULL UNIQUE REFERENCES summarization_jobs(id),
    source_id        UUID            NOT NULL REFERENCES review_sources(id),
    pain_points      JSONB           NOT NULL,
    raw_llm_response TEXT            NOT NULL,
    model_used       VARCHAR(255)    NOT NULL,
    prompt_version   VARCHAR(50)     NOT NULL,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_summaries_organization_id ON summaries(organization_id);
CREATE INDEX idx_summaries_source_id ON summaries(organization_id, source_id);
CREATE INDEX idx_summaries_job_id ON summaries(job_id);
```

**Why `UNIQUE` on `job_id`?** Enforces the 1:1 relationship between a
job and its summary at the database level — not just the service layer.

**Why `source_id` denormalized here?** The dashboard shows summaries
grouped by source. Without `source_id` on this table, every summary
query would need to join through `summarization_jobs`. Denormalization
is intentional and documented.

**Why `pain_points JSONB NOT NULL`?** Must always contain a non-empty array.
Validated before insert at the service layer — the DB constraint ensures
no partial writes slip through.

---

## Indexes Summary

| Table | Index | Purpose |
|-------|-------|---------|
| users | `organization_id` | Tenant filtering |
| users | `email` | Login lookup |
| refresh_tokens | `user_id` | Token-by-user lookup |
| refresh_tokens | `token_hash` | Token validation on every request |
| review_sources | `organization_id` | Tenant filtering |
| review_sources | `(org_id, source_type)` | Dashboard filter by type |
| reviews | `organization_id` | Tenant filtering |
| reviews | `(org_id, source_id)` | Reviews by source |
| reviews | `(org_id, review_date DESC)` | Chronological dashboard queries |
| reviews | `(org_id, rating)` | Filter low-rated reviews for jobs |
| summarization_jobs | `organization_id` | Tenant filtering |
| summarization_jobs | `(org_id, source_id)` | Jobs by source |
| summarization_jobs | `(org_id, status)` | Active job lookup |
| summarization_jobs | `celery_task_id` (partial) | Worker result callback |
| summaries | `organization_id` | Tenant filtering |
| summaries | `(org_id, source_id)` | Summaries by source for dashboard |

---

## Migration Strategy (Alembic)

- Alembic manages all schema changes — **never edit tables manually**.
- One migration file per logical change — do not batch unrelated changes.
- Migration files are committed to git alongside the code change that requires them.
- Migration naming: `YYYY_descriptive_name` e.g. `0001_initial_schema`.

```
alembic/
├── env.py           ← reads DATABASE_URL from settings, imports all models
├── script.py.mako   ← migration file template
└── versions/
    └── 0001_initial_schema.py
```

**Running migrations:**
```bash
# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Generate a new migration after changing models
alembic revision --autogenerate -m "add_column_to_reviews"
```

**Important:** Autogenerate creates a migration file — always review it
before applying. Alembic sometimes misses index changes or generates
incorrect column types for JSONB.

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Main database connection | `postgresql+asyncpg://user:pass@localhost/sentimentpulse` |
| `TEST_DATABASE_URL` | Test database (separate DB, same server) | `postgresql+asyncpg://user:pass@localhost/sentimentpulse_test` |

The async driver `asyncpg` is required for SQLAlchemy 2.0 async sessions.
Use `postgresql+asyncpg://` (not `postgresql://`) in all connection strings.
