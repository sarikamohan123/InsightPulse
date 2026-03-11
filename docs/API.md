# API Reference — SentimentPulse

All endpoints are prefixed with `/api/v1`.

---

## Conventions

### Authentication

Protected endpoints require a JWT access token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Access tokens expire after 15 minutes. Use `POST /auth/refresh` with a valid
refresh token to obtain a new access token.

### Tenant isolation

All tenant-scoped data endpoints operate exclusively within the organization
extracted from the JWT token. A user from Org A can never read, write, or
delete data belonging to Org B. The `organization_id` is never accepted as a
request parameter — it is always derived from the token.

### Request format

All request bodies are JSON. Set `Content-Type: application/json`.

File upload endpoints use `multipart/form-data`.

### Response format

All responses are JSON. Successful responses return the relevant resource or
list. Error responses follow a consistent shape:

```json
{
  "detail": "Human-readable error message"
}
```

### Common HTTP status codes

| Code | Meaning |
|------|---------|
| `200` | OK — request succeeded |
| `201` | Created — resource created |
| `204` | No Content — resource deleted |
| `400` | Bad Request — validation error |
| `401` | Unauthorized — missing or expired token |
| `403` | Forbidden — authenticated but lacks permission |
| `404` | Not Found — resource does not exist in this org |
| `409` | Conflict — duplicate resource |
| `422` | Unprocessable Entity — Pydantic validation failed |
| `500` | Internal Server Error |

---

## Auth

### POST `/auth/register`

Creates a new user and a new organization in a single operation.

**Auth required:** No

**Request body:**

```json
{
  "email": "alice@acme.com",
  "password": "securepassword123",
  "organization_name": "Acme Corp"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `email` | string | yes | Valid email format, globally unique |
| `password` | string | yes | Minimum 8 characters |
| `organization_name` | string | yes | 1–100 characters |

**Response `201`:**

```json
{
  "id": "uuid",
  "email": "alice@acme.com",
  "role": "admin",
  "organization": {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "plan": "free"
  }
}
```

**Errors:**
- `409` — email already registered

---

### POST `/auth/login`

Authenticates a user and returns an access token and a refresh token.

**Auth required:** No

**Request body:**

```json
{
  "email": "alice@acme.com",
  "password": "securepassword123"
}
```

**Response `200`:**

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

**Errors:**
- `401` — invalid credentials
- `403` — account deactivated

---

### POST `/auth/refresh`

Issues a new access token using a valid refresh token.
The refresh token is rotated on use — the old one is invalidated.

**Auth required:** No

**Request body:**

```json
{
  "refresh_token": "eyJ..."
}
```

**Response `200`:**

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

**Errors:**
- `401` — refresh token invalid, expired, or already used

---

### GET `/auth/me`

Returns the currently authenticated user's profile.

**Auth required:** Yes

**Response `200`:**

```json
{
  "id": "uuid",
  "email": "alice@acme.com",
  "role": "admin",
  "is_active": true,
  "organization_id": "uuid",
  "created_at": "2025-03-01T10:00:00Z"
}
```

---

## Organizations

### GET `/organizations/me`

Returns the organization the current user belongs to.

**Auth required:** Yes

**Response `200`:**

```json
{
  "id": "uuid",
  "name": "Acme Corp",
  "slug": "acme-corp",
  "plan": "free",
  "is_active": true,
  "created_at": "2025-03-01T10:00:00Z"
}
```

---

## Sources

Sources represent configured data connections that produce reviews.

### POST `/sources`

Creates a new review source for the current organization.

**Auth required:** Yes — `admin` role required

**Request body:**

```json
{
  "name": "iOS App — Q1 2025",
  "source_type": "csv",
  "config": {}
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | yes | 1–100 characters |
| `source_type` | enum | yes | `csv` \| `appstore` \| `google` \| `twitter` |
| `config` | object | no | Source-specific config (see below) |

**Config by source type:**

| `source_type` | Config shape | Example |
|---------------|-------------|---------|
| `csv` | `{}` or omit | — |
| `appstore` | `{ "app_id": "string" }` | `{ "app_id": "123456789" }` |
| `google` | `{ "place_id": "string" }` | `{ "place_id": "ChIJ..." }` |
| `twitter` | `{ "handle": "string", "hashtags": ["string"] }` | `{ "handle": "acme", "hashtags": ["#acme"] }` |

**Response `201`:**

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "iOS App — Q1 2025",
  "source_type": "csv",
  "config": {},
  "is_active": true,
  "created_at": "2025-03-01T10:00:00Z",
  "updated_at": "2025-03-01T10:00:00Z"
}
```

**Errors:**
- `403` — user is not an admin

---

### GET `/sources`

Lists all active sources for the current organization.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_inactive` | bool | `false` | Include deactivated sources |

**Response `200`:**

```json
[
  {
    "id": "uuid",
    "name": "iOS App — Q1 2025",
    "source_type": "csv",
    "is_active": true,
    "created_at": "2025-03-01T10:00:00Z"
  }
]
```

---

### GET `/sources/{source_id}`

Returns a single source by ID.

**Auth required:** Yes

**Response `200`:** Full source object (same shape as `POST /sources` response)

**Errors:**
- `404` — source not found in this organization

---

### PATCH `/sources/{source_id}`

Updates a source's name or config.

**Auth required:** Yes — `admin` role required

**Request body** (all fields optional):

```json
{
  "name": "iOS App — Q2 2025",
  "config": { "app_id": "987654321" }
}
```

**Response `200`:** Updated source object

**Errors:**
- `403` — user is not an admin
- `404` — source not found in this organization

---

### DELETE `/sources/{source_id}`

Deletes or deactivates a source.

- If the source has **no reviews**: hard delete
- If the source has **reviews**: soft deactivate (`is_active = false`)

**Auth required:** Yes — `admin` role required

**Response `204`:** No content

**Errors:**
- `403` — user is not an admin
- `404` — source not found in this organization

---

## Reviews

### POST `/sources/{source_id}/ingest`

Ingests reviews from a source. For CSV sources, accepts a file upload.
For simulated sources (appstore, google, twitter), triggers the provider
to generate simulated reviews — no file required.

**Auth required:** Yes — `admin` role required

**For CSV sources** — `multipart/form-data`:

```
file: <CSV file>
```

CSV must have headers. Required column: `content`. Optional: `author`,
`rating`, `review_date`, `external_id`.

**For non-CSV sources** — empty JSON body `{}` triggers simulation.

**Response `201`:**

```json
{
  "ingested_count": 47,
  "skipped_count": 3,
  "source_id": "uuid"
}
```

`skipped_count` reflects reviews rejected due to missing `content` or
duplicate `external_id`.

**Errors:**
- `400` — missing or malformed CSV file
- `403` — user is not an admin
- `404` — source not found in this organization
- `409` — source is inactive

---

### GET `/reviews`

Lists reviews for the current organization, filtered by source.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source_id` | UUID | yes | Filter to a specific source |
| `date_from` | date | no | ISO date, earliest `review_date` |
| `date_to` | date | no | ISO date, latest `review_date` |
| `rating_max` | float | no | Include reviews at or below this rating |
| `limit` | int | no | Max results, default `50`, max `200` |
| `offset` | int | no | Pagination offset, default `0` |

**Response `200`:**

```json
{
  "total": 142,
  "limit": 50,
  "offset": 0,
  "items": [
    {
      "id": "uuid",
      "source_id": "uuid",
      "content": "The app crashes every time I open it.",
      "author": "user123",
      "rating": 1.0,
      "review_date": "2025-02-15",
      "created_at": "2025-03-01T10:00:00Z"
    }
  ]
}
```

**Errors:**
- `400` — `source_id` missing
- `404` — source not found in this organization

---

## Jobs

Summarization jobs run asynchronously. Create a job, then poll for status.

### POST `/jobs`

Creates a new summarization job. The job is queued immediately.

**Auth required:** Yes — `admin` role required

**Request body:**

```json
{
  "source_id": "uuid",
  "filters": {
    "date_from": "2025-01-01",
    "date_to": "2025-03-31",
    "max_reviews": 100,
    "rating_max": 3.0
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_id` | UUID | yes | Source to summarize |
| `filters.date_from` | date | no | Earliest `review_date` to include |
| `filters.date_to` | date | no | Latest `review_date` to include |
| `filters.max_reviews` | int | no | Batch size cap, default `100` |
| `filters.rating_max` | float | no | Include reviews at or below this rating |

**Response `201`:**

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "source_id": "uuid",
  "status": "pending",
  "review_count": 0,
  "filters": {
    "source_id": "uuid",
    "date_from": "2025-01-01",
    "date_to": "2025-03-31",
    "max_reviews": 100,
    "rating_max": 3.0
  },
  "celery_task_id": null,
  "error_message": null,
  "started_at": null,
  "completed_at": null,
  "created_at": "2025-03-01T10:00:00Z"
}
```

**Errors:**
- `400` — no reviews match the given filters
- `403` — user is not an admin
- `404` — source not found in this organization
- `409` — a job is already pending or running for this source

---

### GET `/jobs`

Lists all jobs for the current organization.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `source_id` | UUID | — | Filter to a specific source |
| `status` | enum | — | Filter by status: `pending`, `running`, `completed`, `failed` |
| `limit` | int | `20` | Max results |
| `offset` | int | `0` | Pagination offset |

**Response `200`:**

```json
{
  "total": 8,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": "uuid",
      "source_id": "uuid",
      "status": "completed",
      "review_count": 47,
      "created_at": "2025-03-01T10:00:00Z",
      "completed_at": "2025-03-01T10:02:31Z"
    }
  ]
}
```

---

### GET `/jobs/{job_id}`

Returns a single job with full detail. Used for polling job status.

**Auth required:** Yes

**Response `200`:**

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "source_id": "uuid",
  "status": "completed",
  "review_count": 47,
  "filters": { ... },
  "celery_task_id": "celery-uuid",
  "error_message": null,
  "started_at": "2025-03-01T10:01:00Z",
  "completed_at": "2025-03-01T10:02:31Z",
  "created_at": "2025-03-01T10:00:00Z"
}
```

**Polling strategy (frontend):**

Poll `GET /jobs/{job_id}` every 3 seconds while `status` is `pending` or
`running`. Stop polling when `status` is `completed` or `failed`. On
`completed`, fetch the summary via `GET /summaries?job_id={job_id}`.

**Errors:**
- `404` — job not found in this organization

---

## Summaries

### GET `/summaries`

Lists summaries for the current organization.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source_id` | UUID | no | Filter by source |
| `job_id` | UUID | no | Get summary for a specific job |

**Response `200`:**

```json
[
  {
    "id": "uuid",
    "job_id": "uuid",
    "source_id": "uuid",
    "pain_points": [
      "App crashes on launch for users on iOS 17",
      "Login flow is confusing — users cannot find the password reset link",
      "Slow load times reported on all pages"
    ],
    "model_used": "mistralai/Mistral-7B-Instruct-v0.1",
    "prompt_version": "v1",
    "created_at": "2025-03-01T10:02:31Z"
  }
]
```

---

### GET `/summaries/{summary_id}`

Returns a single summary with the full `raw_llm_response` included.

**Auth required:** Yes

**Response `200`:**

```json
{
  "id": "uuid",
  "job_id": "uuid",
  "source_id": "uuid",
  "pain_points": [
    "App crashes on launch for users on iOS 17",
    "Login flow is confusing — users cannot find the password reset link",
    "Slow load times reported on all pages"
  ],
  "raw_llm_response": "Based on the 47 reviews provided, the top pain points are...",
  "model_used": "mistralai/Mistral-7B-Instruct-v0.1",
  "prompt_version": "v1",
  "created_at": "2025-03-01T10:02:31Z"
}
```

`raw_llm_response` is omitted from the list endpoint to keep list payloads small.

**Errors:**
- `404` — summary not found in this organization

---

## Role Permissions Summary

| Endpoint | `member` | `admin` |
|----------|----------|---------|
| `GET /auth/me` | yes | yes |
| `GET /organizations/me` | yes | yes |
| `GET /sources` | yes | yes |
| `GET /sources/{id}` | yes | yes |
| `POST /sources` | no | yes |
| `PATCH /sources/{id}` | no | yes |
| `DELETE /sources/{id}` | no | yes |
| `POST /sources/{id}/ingest` | no | yes |
| `GET /reviews` | yes | yes |
| `GET /jobs` | yes | yes |
| `GET /jobs/{id}` | yes | yes |
| `POST /jobs` | no | yes |
| `GET /summaries` | yes | yes |
| `GET /summaries/{id}` | yes | yes |

---

See `docs/ARCHITECTURE.md` for auth flow and token design.
See `docs/ENTITIES.md` for full field definitions and business rules.
