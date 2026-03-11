# Core Domain Entities

This document defines all core entities in SentimentPulse.
All SQLAlchemy models, Pydantic schemas, and TypeScript types derive from these definitions.
Update this document before changing any model or schema.

---

## Entity Overview

```
Organization
  ├── User (many)
  ├── ReviewSource (many)
  │     └── Review (many)
  ├── SummarizationJob (many)
  │     └── Summary (one)
  └── [all entities carry organization_id — this is the tenant boundary]
```

---

## Multi-tenancy Rule

Every query on Users, ReviewSources, Reviews, SummarizationJobs, and Summaries
MUST include `organization_id` as a filter parameter.

This is enforced at the **repository layer**, not the API layer.
No service or API handler may query tenant-owned data without supplying `organization_id`.

---

## 1. Organization

The root tenant. Every piece of data belongs to an organization.
This is the multi-tenancy boundary — no data ever crosses organizations.

| Field      | Type      | Nullable | Description                       |
|------------|-----------|----------|-----------------------------------|
| id         | UUID      | No       | Primary key                       |
| name       | string    | No       | Display name e.g. "Acme Corp"     |
| slug       | string    | No       | URL-safe unique identifier        |
| plan       | enum      | No       | `free` \| `pro` \| `enterprise`   |
| is_active  | bool      | No       | Soft-disable without deleting     |
| created_at | timestamp | No       | Auto-set on insert                |
| updated_at | timestamp | No       | Auto-set on update                |

**Relationships:** has many Users, ReviewSources, Reviews, SummarizationJobs, Summaries

---

## 2. User

An authenticated identity. Always belongs to exactly one Organization.

| Field           | Type      | Nullable | Description                         |
|-----------------|-----------|----------|-------------------------------------|
| id              | UUID      | No       | Primary key                         |
| organization_id | UUID      | No       | FK → Organization (tenant key)      |
| email           | string    | No       | Unique across the entire system     |
| hashed_password | string    | No       | bcrypt hash — never store plaintext |
| role            | enum      | No       | `admin` \| `member`                 |
| is_active       | bool      | No       | Deactivate without deleting         |
| created_at      | timestamp | No       | Auto-set on insert                  |
| updated_at      | timestamp | No       | Auto-set on update                  |

**Relationships:** belongs to Organization

**Business rules:**
- Email must be unique globally (not just per org)
- Only `admin` users can create/delete sources and trigger summarization jobs
- Deactivated users cannot authenticate even with a valid token

---

## 3. ReviewSource

Represents a configured data source that produces reviews.
One source = one connection to one platform (e.g. one CSV config, one App Store app ID).

| Field           | Type      | Nullable | Description                               |
|-----------------|-----------|----------|-------------------------------------------|
| id              | UUID      | No       | Primary key                               |
| organization_id | UUID      | No       | FK → Organization (tenant key)            |
| name            | string    | No       | Human label e.g. "iOS App — Q1 2025"     |
| source_type     | enum      | No       | `csv` \| `appstore` \| `google` \| `twitter` |
| config          | JSONB     | Yes      | Source-specific config (app_id, handle)   |
| is_active       | bool      | No       | Soft-deactivate instead of hard delete    |
| created_at      | timestamp | No       | Auto-set on insert                        |
| updated_at      | timestamp | No       | Auto-set on update                        |

**Relationships:** belongs to Organization; has many Reviews, SummarizationJobs

**Business rules:**
- `config` schema varies by `source_type` and is validated at the service layer:
  - `csv` — no config required (file uploaded per-ingestion)
  - `appstore` — `{ "app_id": "string" }`
  - `google` — `{ "place_id": "string" }`
  - `twitter` — `{ "handle": "string", "hashtags": ["string"] }`
- Sources with associated reviews **must be soft-deactivated** (`is_active = False`).
  Hard delete is only permitted if the source has zero reviews.
  This prevents orphaned review records.
- Deactivated sources cannot have new reviews ingested or new jobs triggered against them.

---

## 4. Review

A single piece of customer feedback ingested from a ReviewSource.

| Field           | Type      | Nullable | Description                              |
|-----------------|-----------|----------|------------------------------------------|
| id              | UUID      | No       | Primary key                              |
| organization_id | UUID      | No       | FK → Organization (tenant key)           |
| source_id       | UUID      | No       | FK → ReviewSource                        |
| external_id     | string    | Yes      | Original ID from source platform         |
| content         | text      | No       | The review text — required               |
| author          | string    | Yes      | Reviewer name or handle                  |
| rating          | float     | Yes      | Numeric rating (e.g. 1.0–5.0)           |
| review_date     | date      | Yes      | When the review was originally written   |
| raw_metadata    | JSONB     | Yes      | Full original source payload (audit log) |
| created_at      | timestamp | No       | Auto-set on insert                       |

**Relationships:** belongs to Organization, ReviewSource

**Business rules:**
- `content` is required — reviews without text are rejected at ingestion
- `(external_id, source_id)` must be unique to prevent duplicate ingestion
- `organization_id` must match `source.organization_id` — enforced at the service layer

---

## 5. SummarizationJob

An async background task that selects a batch of reviews from a source
and sends them to the LLM provider to extract the top pain points.

| Field           | Type      | Nullable | Description                                    |
|-----------------|-----------|----------|------------------------------------------------|
| id              | UUID      | No       | Primary key                                    |
| organization_id | UUID      | No       | FK → Organization (tenant key)                 |
| source_id       | UUID      | No       | FK → ReviewSource                              |
| status          | enum      | No       | `pending` → `running` → `completed` \| `failed` |
| review_count    | int       | No       | Number of reviews included in this batch       |
| filters         | JSONB     | No       | Criteria used to select the batch (see below)  |
| celery_task_id  | string    | Yes      | Celery task UUID for result backend polling    |
| error_message   | text      | Yes      | Populated on failure for display + debugging   |
| started_at      | timestamp | Yes      | When Celery picked up the task                 |
| completed_at    | timestamp | Yes      | When task finished (success or failure)        |
| created_at      | timestamp | No       | Auto-set on insert                             |

### filters JSONB — structure

The `filters` field documents exactly how the review batch was selected.
It is written at job creation time and never mutated.

```json
{
  "source_id": "uuid-string",
  "date_from": "2025-01-01",
  "date_to":   "2025-03-31",
  "max_reviews": 100,
  "rating_max": 3.0
}
```

| Filter key   | Type   | Required | Description                                      |
|--------------|--------|----------|--------------------------------------------------|
| source_id    | string | Yes      | The source reviews were pulled from              |
| date_from    | string | No       | ISO date — earliest review_date to include       |
| date_to      | string | No       | ISO date — latest review_date to include         |
| max_reviews  | int    | Yes      | Batch size cap (default 100)                     |
| rating_max   | float  | No       | Only include reviews at or below this rating     |

**Future evolution note:**
The `filters` approach documents *how* a batch was selected but not *exactly which* reviews
were included (e.g. if reviews are deleted later). If exact per-review auditability is needed,
this can be evolved to a `job_reviews` join table (columns: `job_id`, `review_id`) without
breaking the rest of the schema. For MVP, `filters` + `review_count` is sufficient.

**Relationships:** belongs to Organization, ReviewSource; has one Summary

**Business rules:**
- Only one active job (`pending` or `running`) per source at a time
- `review_count` must be > 0 — jobs with no matching reviews are rejected
- Status transitions are one-way: `pending → running → completed | failed`
- Failed jobs can be retried by creating a new job record (no status reversal)
- `filters` must be stored at creation time and is immutable after that

---

## 6. Summary

The output produced by a completed SummarizationJob.
Contains the LLM's structured analysis of the review batch.

| Field            | Type      | Nullable | Description                                      |
|------------------|-----------|----------|--------------------------------------------------|
| id               | UUID      | No       | Primary key                                      |
| organization_id  | UUID      | No       | FK → Organization (tenant key)                   |
| job_id           | UUID      | No       | FK → SummarizationJob (1:1)                      |
| source_id        | UUID      | No       | FK → ReviewSource (denormalized for fast queries)|
| pain_points      | JSONB     | No       | Array of strings — top 3 pain points from LLM   |
| raw_llm_response | text      | No       | Full LLM output preserved for audit/debug        |
| model_used       | string    | No       | e.g. `"mistralai/Mistral-7B-Instruct-v0.1"`      |
| prompt_version   | string    | No       | Prompt template version e.g. `"v1"`, `"v2"`      |
| created_at       | timestamp | No       | Auto-set on insert                               |

**Relationships:** belongs to Organization, SummarizationJob, ReviewSource

**Business rules:**
- One Summary per Job — 1:1 relationship, enforced by unique constraint on `job_id`
- `pain_points` must be a non-empty JSON array (validated before insert)
- `source_id` is denormalized here to allow fast dashboard queries without joining through Job
- `prompt_version` must be set from the active prompt config at task execution time —
  never hardcoded. This allows output comparison when the prompt template changes.
- `raw_llm_response` is always stored even if parsing partially fails — supports debugging

---

## Status Enums

```
Organization.plan    : free | pro | enterprise
User.role            : admin | member
ReviewSource.type    : csv | appstore | google | twitter
SummarizationJob.status : pending | running | completed | failed
```
