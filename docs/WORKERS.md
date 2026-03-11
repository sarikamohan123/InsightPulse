# Workers — SentimentPulse

This document covers the Celery setup, task lifecycle, job status transitions,
retry configuration, Redis as broker and result backend, and how workers
behave during testing.

---

## Why Celery?

LLM API calls are slow — a batch of 100 reviews sent to HuggingFace can take
10–30 seconds. If this ran synchronously inside a FastAPI request:
- The HTTP request would hang for 30 seconds
- The browser would show a spinner with no feedback
- Any network interruption would kill the job

Celery moves the work off the request thread:
1. The API creates a job record and dispatches a Celery task (< 100ms)
2. The API returns immediately with `{ "job_id": "...", "status": "pending" }`
3. A Celery worker picks up the task and does the slow work in the background
4. The frontend polls `GET /jobs/{id}` until status changes to `completed`

```
HTTP Request (fast)          Celery Worker (slow, background)
─────────────────            ────────────────────────────────
POST /jobs                   picks up task
  → create job record        → updates status: running
  → dispatch task            → queries reviews
  → return 202 Accepted      → calls LLM API (10–30s)
                             → writes summary
                             → updates status: completed
```

---

## Redis: Broker and Result Backend

Redis serves two roles:

| Role | What it does |
|---|---|
| **Broker** | Receives dispatched tasks from FastAPI, queues them for workers |
| **Result backend** | Stores task outcomes so FastAPI can check if a task succeeded or failed |

Using Redis for both keeps the infrastructure simple — one service, two roles.
The alternative (separate RabbitMQ broker + Redis results) adds operational
complexity without benefit at this scale.

```
FastAPI → Redis (broker) → Celery Worker → Redis (result backend)
                                         → PostgreSQL (job + summary records)
```

---

## Celery Configuration

```python
# app/workers/celery_app.py

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "sentimentpulse",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks.summarization",
             "app.workers.tasks.ingestion"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Result expiry — keep task results in Redis for 1 hour
    result_expires=3600,

    # Routing — all tasks go to the default queue for now
    task_default_queue="default",

    # Acknowledgement — only mark task done after it completes (not on receipt)
    # This prevents lost tasks if the worker crashes mid-execution
    task_acks_late=True,

    # Reject tasks that are not acknowledged (worker crash) back to the queue
    task_reject_on_worker_lost=True,
)
```

**Why `task_acks_late=True`?**
By default, Celery marks a task as "received" the moment a worker picks it up.
If the worker crashes before finishing, the task is lost. `task_acks_late`
delays acknowledgement until the task completes — a crash causes the task
to be requeued automatically.

**Why `result_expires=3600`?**
Celery task results stored in Redis are not needed permanently — the canonical
job state lives in PostgreSQL. One hour is enough for the frontend to poll
the result. After that, Redis reclaims the memory.

---

## Task: Summarization

```python
# app/workers/tasks/summarization.py

from celery import shared_task
from app.workers.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,          # exponential: 5s, 10s, 20s
    retry_backoff_max=60,        # cap at 60 seconds
    retry_jitter=True,           # add randomness to avoid thundering herd
)
def run_summarization(self, job_id: str) -> dict:
    """
    Background task that:
    1. Marks the job as running
    2. Fetches reviews using stored filters
    3. Calls the LLM provider
    4. Writes the summary
    5. Marks the job as completed (or failed on unrecoverable error)

    Receives job_id as a string (Celery serialises to JSON — UUIDs must be strings).
    """
    import asyncio
    from uuid import UUID
    from app.db.session import get_sync_session
    from app.repositories.job_repo import JobRepository
    from app.repositories.review_repo import ReviewRepository
    from app.repositories.summary_repo import SummaryRepository
    from app.providers.llm.huggingface import HuggingFaceLLMProvider
    from app.providers.llm.mock import MockLLMProvider
    from app.core.config import settings
    from app.services.summary_service import SummaryService

    logger.info("summarization_task_started", job_id=job_id)

    llm_provider = (
        HuggingFaceLLMProvider(api_key=settings.huggingface_api_key)
        if settings.huggingface_api_key
        else MockLLMProvider()
    )

    with get_sync_session() as session:
        job_repo = JobRepository()
        review_repo = ReviewRepository()
        summary_repo = SummaryRepository()
        service = SummaryService(job_repo, review_repo, summary_repo, llm_provider)

        try:
            asyncio.run(service.execute_summarization(UUID(job_id), session))
            logger.info("summarization_task_completed", job_id=job_id)
            return {"status": "completed", "job_id": job_id}

        except Exception as exc:
            logger.error("summarization_task_failed", job_id=job_id, error=str(exc))
            asyncio.run(
                job_repo.mark_failed(UUID(job_id), str(exc), session)
            )
            raise self.retry(exc=exc)
```

**Why pass `job_id` as a string, not a UUID?**
Celery serialises task arguments to JSON. `UUID` objects are not JSON-serialisable.
Always pass UUIDs as strings and convert with `UUID(job_id)` inside the task.

**Why `bind=True`?**
Gives the task access to `self`, which is needed for `self.retry()`.
Without `bind=True`, you cannot call retry from within the task.

**Why `retry_jitter=True`?**
If multiple jobs fail at the same time (e.g. HuggingFace goes down),
all retries would fire at exactly the same moment — a thundering herd.
Jitter adds a small random delay so retries spread out over time.

---

## Task: Ingestion

```python
# app/workers/tasks/ingestion.py

@celery_app.task(bind=True, max_retries=2, retry_backoff=True)
def run_ingestion(self, source_id: str, organization_id: str) -> dict:
    """
    Background task for fetching and storing reviews from a source.
    Used for non-CSV sources (AppStore, Google, Twitter) where
    fetching may be slow or rate-limited.

    CSV ingestion runs synchronously (file is already in memory).
    """
    ...
```

CSV ingestion does not use a Celery task — the file is already uploaded
and in memory, so it can be processed synchronously within the request.
Only network-dependent sources (AppStore, Google, Twitter) use this task.

---

## Job Status Transitions

```
         POST /jobs
              │
         ┌────▼─────┐
         │  pending  │  Job created, task dispatched to Redis
         └────┬──────┘
              │  Worker picks up task
         ┌────▼─────┐
         │  running  │  LLM call in progress
         └────┬──────┘
              │
       ┌──────┴──────┐
       │             │
  ┌────▼─────┐  ┌────▼─────┐
  │completed │  │  failed  │  error_message populated
  └──────────┘  └──────────┘
```

Rules:
- Transitions are **one-way** — no backwards movement
- `failed` jobs can be retried by creating a **new job record** (not resetting status)
- Only one `pending` or `running` job per source at a time (service-layer rule)
- `started_at` is set when status moves to `running`
- `completed_at` is set when status moves to `completed` or `failed`

---

## Polling from the Frontend

The frontend uses TanStack Query's `refetchInterval` to poll job status:

```typescript
// hooks/useJobPolling.ts
const { data: job } = useQuery({
  queryKey: ["job", jobId],
  queryFn: () => fetchJob(jobId),
  refetchInterval: (data) => {
    // Poll every 3 seconds while job is active, stop when terminal
    const active = data?.status === "pending" || data?.status === "running"
    return active ? 3000 : false
  },
})
```

Polling stops automatically when status is `completed` or `failed`.
No manual cleanup required — TanStack Query handles it.

---

## Worker Startup

```bash
# Start the Celery worker locally (outside Docker)
celery -A app.workers.celery_app worker --loglevel=info

# Start with concurrency (4 parallel workers)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

# Monitor tasks in terminal
celery -A app.workers.celery_app events
```

In Docker Compose, the worker runs as a separate service using the same
backend image — it shares all code with the API but starts with the
`celery worker` command instead of `uvicorn`.

---

## Testing: task_always_eager

In the test environment, Celery tasks run synchronously in the same process.
No Redis, no worker process needed.

```python
# app/core/config.py (test settings)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True  # re-raises exceptions instead of swallowing them
```

```python
# app/workers/celery_app.py
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_eager_propagates,
)
```

With `task_always_eager=True`:
- `run_summarization.delay(job_id)` executes immediately, inline
- The test can assert on the job status without polling
- The `MockLLMProvider` is used (injected via `dependency_overrides`)
- No Redis or worker process needs to be running

This is how `tests/integration/test_worker_processing.py` works — it triggers
a job via the API, and the task completes before the next line of the test runs.

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `CELERY_TASK_ALWAYS_EAGER` | Run tasks inline (tests only) | `False` |
| `CELERY_TASK_EAGER_PROPAGATES` | Re-raise task exceptions (tests only) | `False` |
