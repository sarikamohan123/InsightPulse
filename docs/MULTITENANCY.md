# Multi-tenancy — SentimentPulse

This document explains how tenant isolation is implemented across every layer
of the application. Read this before writing any code that touches tenant-owned data.

---

## Strategy: Row-Level Multi-tenancy

SentimentPulse uses **row-level multi-tenancy** — all tenants share the same
PostgreSQL database and the same tables. Every tenant-owned row is tagged with
`organization_id`, and every query filters by it.

This is different from schema-per-tenant (where each org gets its own Postgres
schema) or database-per-tenant (where each org gets its own database instance).

### Why row-level?

| Approach | Isolation | Complexity | Suitable for |
|---|---|---|---|
| Row-level (our choice) | Good | Low | SaaS MVPs, learning, most B2B apps |
| Schema-per-tenant | Strong | Medium | Regulated industries needing stronger separation |
| Database-per-tenant | Strongest | High | Enterprise contracts requiring full isolation |

Row-level is the right starting point. If a customer later requires schema
isolation (e.g. for compliance), it can be added without a full rewrite —
the service and API layers remain unchanged.

---

## The Trust Boundary

```
┌─────────────────────────────────────────────┐
│  JWT Token                                  │
│  { "sub": "user-uuid",                      │
│    "org": "organization-uuid",              │
│    "role": "admin" }                        │
└────────────────────┬────────────────────────┘
                     │ extracted by
┌────────────────────▼────────────────────────┐
│  api/deps.py                                │
│  get_current_user() → User                  │
│  get_organization_id() → UUID               │
└────────────────────┬────────────────────────┘
                     │ passed explicitly to
┌────────────────────▼────────────────────────┐
│  Service Layer                              │
│  review_service.list_reviews(org_id, ...)   │
└────────────────────┬────────────────────────┘
                     │ passed explicitly to
┌────────────────────▼────────────────────────┐
│  Repository Layer  ← isolation enforced here│
│  review_repo.get_all(org_id, session, ...)  │
│  WHERE organization_id = :org_id            │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│  PostgreSQL                                 │
│  SELECT * FROM reviews                      │
│  WHERE organization_id = 'uuid'             │
└─────────────────────────────────────────────┘
```

The `organization_id` is never trusted from the request body.
It always comes from the verified JWT token.

---

## Layer-by-Layer Implementation

### 1. JWT Token (trust source)

When a user logs in, we embed `organization_id` in the JWT payload:

```python
# app/core/security.py
def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "org": str(user.organization_id),  # tenant identity baked in
        "role": user.role,
        "exp": datetime.utcnow() + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")
```

**Why embed `organization_id` in the token?**
Avoids a database lookup on every request. The org identity is verified
at login time and signed into the token — no extra query needed per request.

---

### 2. Dependency Injection (extraction layer)

`api/deps.py` is the only place in the codebase that reads from the JWT.
Everything downstream receives `organization_id` as a plain `UUID` argument.

```python
# app/api/deps.py
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(token)          # raises 401 if invalid
    user = await user_repo.get_by_id(
        user_id=UUID(payload["sub"]),
        session=session,
    )
    if not user or not user.is_active:
        raise HTTPException(status_code=401)
    return user


async def get_organization_id(
    current_user: User = Depends(get_current_user),
) -> UUID:
    return current_user.organization_id           # extracted from JWT, not request
```

**Why a dedicated `get_organization_id` dependency?**
It makes the intent explicit. Any route that requires tenant isolation
declares it with `org_id: UUID = Depends(get_organization_id)`.
Routes that do not need it (e.g. `/health`) simply don't declare it.

---

### 3. API Layer (passes org_id down, never resolves it)

API routes receive `org_id` from the dependency and pass it to the service.
They never query the database directly.

```python
# app/api/v1/reviews.py
@router.get("/reviews")
async def list_reviews(
    source_id: UUID,
    org_id: UUID = Depends(get_organization_id),    # from JWT
    service: ReviewService = Depends(get_review_service),
) -> list[ReviewResponse]:
    return await service.list_reviews(
        organization_id=org_id,
        source_id=source_id,
    )
```

Notice: `organization_id` is never read from the query string or request body.
A client cannot pass `?organization_id=someone-elses-uuid` to access another
tenant's data — the value always comes from their own verified token.

---

### 4. Service Layer (business logic, passes org_id to repos)

Services receive `organization_id` as an explicit parameter on every method
that touches tenant data. They pass it through to repositories unchanged.

```python
# app/services/review_service.py
class ReviewService:
    def __init__(self, review_repo: ReviewRepository):
        self._repo = review_repo

    async def list_reviews(
        self,
        organization_id: UUID,    # required — never has a default
        source_id: UUID,
        session: AsyncSession,
    ) -> list[Review]:
        return await self._repo.get_by_source(
            organization_id=organization_id,
            source_id=source_id,
            session=session,
        )
```

**Why pass `organization_id` explicitly instead of reading it from a context var?**
Explicit parameters are testable. A unit test can call `list_reviews(org_id=X)`
directly without mocking a request context. Context variables (like Python's
`contextvars`) hide the data flow and make tests harder to write.

---

### 5. Repository Layer (enforcement point)

This is where tenant isolation is actually enforced. Every query that touches
a tenant-owned table includes `WHERE organization_id = :org_id`.

```python
# app/repositories/review_repo.py
class ReviewRepository(BaseRepository[Review]):

    async def get_by_source(
        self,
        organization_id: UUID,    # required parameter — never optional
        source_id: UUID,
        session: AsyncSession,
    ) -> list[Review]:
        result = await session.execute(
            select(Review)
            .where(Review.organization_id == organization_id)  # tenant filter
            .where(Review.source_id == source_id)
            .order_by(Review.review_date.desc())
        )
        return result.scalars().all()
```

**Why enforce at the repository layer instead of a Postgres Row Level Security policy?**

| Approach | Enforcement | Tradeoff |
|---|---|---|
| Repository layer (our choice) | Application code | Visible, testable, debuggable |
| Postgres RLS | Database | Stronger guarantee, but harder to debug and test |

RLS is a valid future addition (documented below). For this project,
repository-layer enforcement is the right choice — it's transparent,
easy to test, and covers all access patterns.

---

## What Tenant-Owned Tables Look Like

Every one of these tables has `organization_id NOT NULL`:

| Table | Tenant-owned? |
|---|---|
| `organizations` | No — this IS the tenant |
| `users` | Yes |
| `review_sources` | Yes |
| `reviews` | Yes |
| `summarization_jobs` | Yes |
| `summaries` | Yes |
| `refresh_tokens` | No — scoped to user, not org |

---

## Cross-Tenant Validation

Some operations require verifying that related records belong to the same tenant.

**Example:** When creating a SummarizationJob, the `source_id` in the request
must belong to the requesting org — not another org's source.

```python
# app/services/job_service.py
async def create_job(
    self,
    organization_id: UUID,
    source_id: UUID,
    filters: JobFilters,
    session: AsyncSession,
) -> SummarizationJob:
    # Fetch source WITH org_id filter — returns None if source belongs to another org
    source = await self._source_repo.get_by_id(
        organization_id=organization_id,
        source_id=source_id,
        session=session,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    # ... continue with job creation
```

The `get_by_id` call includes `organization_id` — so if the source exists
but belongs to a different org, it returns `None` (not a 403, to avoid
confirming the record exists). This is standard practice for multi-tenant APIs.

---

## Testing Tenant Isolation

The primary integration test for multi-tenancy lives in:
`tests/integration/test_org_isolation.py`

It verifies that:
- Org A's user cannot read Org B's reviews
- Org A's user cannot trigger a job on Org B's source
- Org A's user cannot see Org B's summaries
- Cross-tenant `source_id` injection returns 404 (not 403 or 500)

```python
# tests/integration/test_org_isolation.py (structure)
async def test_org_a_cannot_read_org_b_reviews(client, org_factory, auth_headers):
    org_a, headers_a = await org_factory(), await auth_headers(org="a")
    org_b, headers_b = await org_factory(), await auth_headers(org="b")

    # Create a review belonging to org_b
    # Attempt to read it as org_a
    response = client.get("/api/v1/reviews", headers=headers_a,
                          params={"source_id": org_b_source_id})
    assert response.status_code == 200
    assert response.json() == []    # empty — not 403, not org_b's data
```

Returning an empty list (not 403) on cross-tenant queries is intentional —
it does not confirm or deny that the source exists in another org.

---

## Future: Postgres Row Level Security (RLS)

RLS can be layered on top of this design without changing any application code.
It would add a database-level guarantee that even a buggy query cannot
return another tenant's data.

When ready, the migration would:
1. Enable RLS on each tenant-owned table
2. Create a policy: `USING (organization_id = current_setting('app.org_id')::uuid)`
3. Set `app.org_id` at the start of each database session in `db/session.py`

This is a pure infrastructure addition — services and repositories remain unchanged.
