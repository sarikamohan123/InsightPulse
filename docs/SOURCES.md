# Source Providers — SentimentPulse

This document covers the source provider abstraction, the shared `ReviewData`
contract, how each simulated source generates data, field mapping per source,
and how to add a real connector in the future.

---

## Why an Abstraction Layer?

Each data source (CSV, App Store, Google, Twitter) has a completely different
raw data format. Without abstraction, the ingestion service would need to know
about every source format — a new source means changing existing service code.

The `SourceProvider` ABC solves this:
- Every provider returns the same `ReviewData` shape
- The ingestion service never knows which source it is talking to
- Adding a real App Store connector means creating one new file

```
ReviewService / IngestionTask
        │
        └── depends on SourceProvider (ABC)
                    │
                    ├── CSVProvider          (file upload)
                    ├── AppStoreProvider     (simulated)
                    ├── GoogleProvider       (simulated)
                    └── TwitterProvider      (simulated)
```

---

## Provider Interface

```python
# app/providers/sources/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum


class SourceType(str, Enum):
    CSV       = "csv"
    APPSTORE  = "appstore"
    GOOGLE    = "google"
    TWITTER   = "twitter"


@dataclass
class ReviewData:
    """
    The shared contract all source providers must return.
    Field names map directly to the Review model.
    Optional fields may be None if the source does not provide them.
    """
    external_id:   str | None       # original ID from the source platform
    content:       str              # required — the review text
    author:        str | None       # reviewer name or handle
    rating:        float | None     # numeric rating (1.0–5.0), None if not applicable
    review_date:   date | None      # when the review was written
    raw_metadata:  dict | None      # full original payload preserved for audit


class SourceProvider(ABC):
    """
    Abstract base class for all review source providers.

    SOLID — ISP: minimal interface. Providers implement exactly two things.
    SOLID — OCP: add a new source by implementing this class in a new file.
    """

    @abstractmethod
    async def fetch_reviews(self) -> list[ReviewData]:
        """
        Fetches or generates reviews from the source.
        Returns a list of ReviewData — never raises on empty results.
        """
        ...

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """The type identifier for this provider."""
        ...
```

`ReviewData` is the single normalisation contract. Every provider, regardless
of how different its raw format is, must map its data to this shape before
returning. The ingestion service writes `ReviewData` fields directly to the
`Review` model — no further mapping needed upstream.

---

## CSVProvider

Parses an uploaded CSV file. This is the simplest provider and the first
one implemented because it requires no external API or simulation logic.

### Expected CSV format

```
external_id,content,author,rating,review_date
rev_001,"App crashes on startup",Jane D.,1.0,2025-01-15
rev_002,"Love the new dashboard",John S.,5.0,2025-01-16
rev_003,"Confusing navigation",Alice K.,2.5,2025-01-17
```

All columns except `content` are optional. Missing columns are filled with `None`.

### Field mapping

| CSV column    | ReviewData field | Notes |
|---------------|-----------------|-------|
| `external_id` | `external_id`   | Optional — used for deduplication |
| `content`     | `content`       | Required — rows without content are skipped |
| `author`      | `author`        | Optional |
| `rating`      | `rating`        | Optional, parsed as float, validated 0.0–5.0 |
| `review_date` | `review_date`   | Optional, parsed as ISO date (YYYY-MM-DD) |
| (entire row)  | `raw_metadata`  | Stored as dict for audit |

### Implementation notes

```python
# app/providers/sources/csv_provider.py

class CSVProvider(SourceProvider):
    """
    Parses a CSV file uploaded by the user.
    Rows with missing or empty `content` are skipped with a warning logged.
    Rows with invalid `rating` values are accepted with rating=None.
    """

    def __init__(self, file_content: bytes) -> None:
        self._file_content = file_content

    @property
    def source_type(self) -> SourceType:
        return SourceType.CSV

    async def fetch_reviews(self) -> list[ReviewData]:
        # parse CSV, skip invalid rows, map to ReviewData
        ...
```

**Why accept `file_content: bytes` in `__init__`?**
The CSV is uploaded via HTTP. The API handler reads the file bytes and
passes them to the provider. The provider does not know about HTTP or
file storage — it only knows how to parse bytes. Clean separation.

---

## AppStoreProvider (Simulated)

Simulates App Store reviews. Generates realistic-looking iOS app reviews
with ratings weighted toward low scores to give the LLM something meaningful
to summarise.

### Simulated data shape (raw)

```json
{
  "id": "AS-00123",
  "title": "Keeps crashing on iPhone 14",
  "body": "Every time I open the app it crashes within 30 seconds...",
  "rating": 1,
  "reviewer": "frustrated_user_99",
  "date": "2025-02-10",
  "version": "2.3.1"
}
```

### Field mapping

| App Store field | ReviewData field  | Notes |
|-----------------|------------------|-------|
| `id`            | `external_id`    | Prefixed with `AS-` |
| `title + body`  | `content`        | Concatenated: `"{title}. {body}"` |
| `reviewer`      | `author`         | |
| `rating`        | `rating`         | Integer 1–5 cast to float |
| `date`          | `review_date`    | Parsed as ISO date |
| (full object)   | `raw_metadata`   | Preserved for audit |

### Simulation behaviour

- Generates between 50–150 reviews per call
- Rating distribution: 40% one-star, 20% two-star, 20% three-star,
  10% four-star, 10% five-star — skewed negative to produce useful pain points
- Review content drawn from a small bank of realistic templates with
  randomised product names, feature mentions, and frustration phrases
- Seeded with `source_id` so the same source always generates the same reviews
  (deterministic for testing)

---

## GoogleProvider (Simulated)

Simulates Google Maps / Yelp-style business reviews. Longer, more conversational
content than App Store reviews. Ratings skewed toward 3-star (mixed sentiment)
to give the LLM nuanced material.

### Simulated data shape (raw)

```json
{
  "review_id": "GR-00456",
  "text": "The service was okay but the wait time was unacceptable...",
  "stars": 3,
  "author_name": "LocalGuide_Maria",
  "published_at": "2025-01-22",
  "helpful_votes": 4
}
```

### Field mapping

| Google field    | ReviewData field | Notes |
|-----------------|-----------------|-------|
| `review_id`     | `external_id`   | Prefixed with `GR-` |
| `text`          | `content`       | |
| `author_name`   | `author`        | |
| `stars`         | `rating`        | Integer 1–5 cast to float |
| `published_at`  | `review_date`   | |
| (full object)   | `raw_metadata`  | |

---

## TwitterProvider (Simulated)

Simulates social media mentions — shorter content, no ratings, hashtags
and @mentions present. Useful for showing the system handles sources
where `rating` is always `None`.

### Simulated data shape (raw)

```json
{
  "tweet_id": "TW-00789",
  "text": "@SentimentApp your onboarding flow is way too complicated 😤 #feedback",
  "username": "tech_reviewer_sam",
  "created_at": "2025-03-01T14:22:00Z",
  "likes": 12,
  "retweets": 3
}
```

### Field mapping

| Twitter field | ReviewData field | Notes |
|---------------|-----------------|-------|
| `tweet_id`    | `external_id`   | Prefixed with `TW-` |
| `text`        | `content`       | Hashtags and @mentions preserved |
| `username`    | `author`        | |
| (none)        | `rating`        | Always `None` — social posts have no rating |
| `created_at`  | `review_date`   | Parsed from ISO datetime, date portion only |
| (full object) | `raw_metadata`  | |

**Why keep content with hashtags and @mentions?**
The LLM prompt instructs the model to identify pain points from the text.
Hashtags provide signal (`#feedback`, `#bugreport`). Removing them would
lose information.

---

## Ingestion Flow

```
1. User selects a source + optional filters in the UI
2. POST /sources/{id}/ingest
3. SourceService selects the correct provider via source_type
4. provider.fetch_reviews() returns list[ReviewData]
5. ReviewService filters out duplicates (checks external_id + source_id)
6. Remaining reviews are bulk-inserted with organization_id
7. Response: { "ingested": 94, "skipped_duplicates": 6 }
```

The service layer selects the provider using a simple registry:

```python
# app/services/source_service.py

PROVIDER_REGISTRY: dict[SourceType, type[SourceProvider]] = {
    SourceType.CSV:      CSVProvider,
    SourceType.APPSTORE: AppStoreProvider,
    SourceType.GOOGLE:   GoogleProvider,
    SourceType.TWITTER:  TwitterProvider,
}

def get_provider(source: ReviewSource, **kwargs) -> SourceProvider:
    provider_class = PROVIDER_REGISTRY.get(source.source_type)
    if provider_class is None:
        raise ValueError(f"Unknown source type: {source.source_type}")
    return provider_class(**kwargs)
```

Adding a new source type = add one entry to `PROVIDER_REGISTRY`.
The service, API, and database do not change.

---

## Adding a Real Connector

To replace a simulated provider with a real API (e.g. actual App Store
Connect API):

1. Create `app/providers/sources/appstore_real_provider.py`
2. Implement `SourceProvider` — define `fetch_reviews()` and `source_type`
3. Map the real API response fields to `ReviewData`
4. Update `PROVIDER_REGISTRY` to point to the new class
5. Add any required API credentials to `config.py` and `.env.example`

The ingestion service, review service, and all tests remain unchanged.
Existing CSV and simulated providers continue to work — no regression risk.

---

## File Structure

```
app/providers/sources/
├── base.py               ← SourceProvider ABC + ReviewData + SourceType enum
├── csv_provider.py       ← parses uploaded CSV bytes
├── appstore_provider.py  ← simulates App Store reviews
├── google_provider.py    ← simulates Google/Yelp-style reviews
└── twitter_provider.py   ← simulates social mentions
```
