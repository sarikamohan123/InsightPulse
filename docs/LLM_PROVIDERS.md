# LLM Providers — SentimentPulse

This document covers the LLM provider abstraction, how each provider works,
prompt versioning, retry strategy, and how to add a new provider.

---

## Why an Abstraction Layer?

The LLM market moves fast. Models change, APIs change, costs change.
Hardcoding a call to the HuggingFace API inside a service means:
- You cannot test without a real API key and internet access
- Swapping to a different model or provider requires changing business logic
- There is no way to run the full job flow in CI

The provider abstraction solves all three. Services depend on `LLMProvider`
(an abstract base class). The concrete implementation — HuggingFace or Mock —
is injected at runtime by FastAPI's dependency system.

```
SummaryService
     │
     └── depends on LLMProvider (ABC)
               │
               ├── HuggingFaceLLMProvider  (production)
               └── MockLLMProvider          (dev + tests)
```

---

## Provider Interface

```python
# app/providers/llm/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SummaryResult:
    pain_points: list[str]      # top 3 pain points extracted by LLM
    raw_response: str           # full LLM output — preserved for audit
    model_used: str             # e.g. "mistralai/Mistral-7B-Instruct-v0.1"
    prompt_version: str         # e.g. "v1" — which prompt template was used


class LLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    SOLID — ISP: this interface is minimal. Implementations are never
    forced to carry methods they do not use.

    SOLID — OCP: add a new provider by implementing this class.
    No existing code changes.
    """

    @abstractmethod
    async def summarize(self, reviews: list[str]) -> SummaryResult:
        """
        Takes a batch of review strings.
        Returns structured pain points + audit fields.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name for logging."""
        ...
```

`SummaryResult` is a plain dataclass — no database or HTTP dependency.
It is the contract between the provider and the service layer.

---

## MockLLMProvider

Used in local development (no API key) and all tests.
Returns deterministic output so tests can make reliable assertions.

```python
# app/providers/llm/mock.py

from app.providers.llm.base import LLMProvider, SummaryResult
from app.core.config import ACTIVE_PROMPT_VERSION


class MockLLMProvider(LLMProvider):
    """
    Returns predictable fake output. No network calls, no API key required.
    Suitable for development and all automated tests.
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    async def summarize(self, reviews: list[str]) -> SummaryResult:
        return SummaryResult(
            pain_points=[
                "Mock pain point 1: slow performance",
                "Mock pain point 2: confusing UI",
                "Mock pain point 3: missing features",
            ],
            raw_response=(
                f"[MOCK] Processed {len(reviews)} reviews. "
                "Top issues: performance, UI clarity, feature gaps."
            ),
            model_used="mock-provider",
            prompt_version=ACTIVE_PROMPT_VERSION,
        )
```

**Why deterministic output?**
Tests that assert `pain_points[0] == "Mock pain point 1: slow performance"`
will always pass. Non-deterministic mocks make flaky tests.

---

## HuggingFaceLLMProvider

Calls the HuggingFace Inference API with `Mistral-7B-Instruct`.
Includes retry logic with exponential backoff for rate limit errors.

```python
# app/providers/llm/huggingface.py

import asyncio
import httpx
from app.providers.llm.base import LLMProvider, SummaryResult
from app.core.config import settings, ACTIVE_PROMPT_VERSION
from app.core.logging import get_logger

logger = get_logger(__name__)

HF_INFERENCE_URL = (
    "https://api-inference.huggingface.co/models/"
    "mistralai/Mistral-7B-Instruct-v0.1"
)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — doubles each attempt: 2s, 4s, 8s


class HuggingFaceLLMProvider(LLMProvider):

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @property
    def provider_name(self) -> str:
        return "huggingface"

    async def summarize(self, reviews: list[str]) -> SummaryResult:
        prompt = self._build_prompt(reviews)
        raw_response = await self._call_with_retry(prompt)
        pain_points = self._parse_pain_points(raw_response)

        return SummaryResult(
            pain_points=pain_points,
            raw_response=raw_response,
            model_used="mistralai/Mistral-7B-Instruct-v0.1",
            prompt_version=ACTIVE_PROMPT_VERSION,
        )

    def _build_prompt(self, reviews: list[str]) -> str:
        """
        Builds the instruction prompt for Mistral-7B-Instruct.
        The [INST] / [/INST] tags are required by this model's chat format.
        prompt_version is tracked so output can be reproduced if the
        template changes in a future version.
        """
        reviews_text = "\n---\n".join(reviews)
        return (
            f"[INST] You are analyzing customer feedback. "
            f"Below are {len(reviews)} customer reviews:\n\n"
            f"{reviews_text}\n\n"
            f"Identify the top 3 pain points mentioned most frequently. "
            f"Reply with a numbered list only. No explanation. [/INST]"
        )

    async def _call_with_retry(self, prompt: str) -> str:
        """
        Calls HuggingFace API with exponential backoff on rate limit (429)
        or transient server errors (503).
        Raises on permanent failures or exhausted retries.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        HF_INFERENCE_URL,
                        headers=self._headers,
                        json={"inputs": prompt},
                    )

                if response.status_code == 200:
                    data = response.json()
                    return data[0]["generated_text"]

                if response.status_code in (429, 503):
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(
                        "huggingface_rate_limited",
                        attempt=attempt,
                        status=response.status_code,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Non-retryable error
                logger.error(
                    "huggingface_api_error",
                    status=response.status_code,
                    body=response.text,
                )
                response.raise_for_status()

            except httpx.TimeoutException:
                logger.warning("huggingface_timeout", attempt=attempt)
                if attempt == MAX_RETRIES:
                    raise

        raise RuntimeError(
            f"HuggingFace API failed after {MAX_RETRIES} attempts"
        )

    def _parse_pain_points(self, raw_response: str) -> list[str]:
        """
        Parses the numbered list from the LLM response.
        Falls back gracefully if the format is unexpected.
        Returns at least one item — never an empty list.
        """
        lines = [
            line.strip()
            for line in raw_response.strip().splitlines()
            if line.strip() and line.strip()[0].isdigit()
        ]
        pain_points = lines[:3] if lines else [raw_response.strip()]

        logger.info(
            "llm_summarization_complete",
            pain_point_count=len(pain_points),
            prompt_version=ACTIVE_PROMPT_VERSION,
        )
        return pain_points
```

---

## Provider Selection — Dependency Injection

The active provider is selected in `api/deps.py` based on whether
`HUGGINGFACE_API_KEY` is set. Services never make this decision themselves.

```python
# app/api/deps.py

def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    if settings.huggingface_api_key:
        return HuggingFaceLLMProvider(api_key=settings.huggingface_api_key)
    return MockLLMProvider()
```

This means:
- **No API key configured** → `MockLLMProvider` used automatically
- **API key present** → `HuggingFaceLLMProvider` used
- **In tests** → `app.dependency_overrides[get_llm_provider]` forces `MockLLMProvider`
  regardless of environment variables

---

## Prompt Versioning

Prompt templates are versioned so LLM output is reproducible and comparable.

```python
# app/core/config.py

ACTIVE_PROMPT_VERSION = "v1"
```

Every `SummaryResult` carries `prompt_version`. Every `Summary` row stores it.

When you change the prompt template:
1. Increment `ACTIVE_PROMPT_VERSION` to `"v2"`
2. Update `_build_prompt()` in `HuggingFaceLLMProvider`
3. Old summaries retain `prompt_version="v1"` — you can compare outputs
4. New jobs produce summaries with `prompt_version="v2"`

This allows A/B analysis of prompt quality over time without losing history.

---

## Retry Strategy

| Scenario | Behaviour |
|---|---|
| HTTP 200 | Return immediately |
| HTTP 429 (rate limited) | Wait `2^attempt` seconds, retry up to 3 times |
| HTTP 503 (service unavailable) | Same as 429 |
| Timeout | Retry up to 3 times, then raise |
| HTTP 4xx (except 429) | Raise immediately — these are permanent errors |
| 3 retries exhausted | Raise `RuntimeError` — Celery task catches this and sets job status = failed |

Exponential backoff: attempt 1 waits 2s, attempt 2 waits 4s, attempt 3 waits 8s.

---

## Adding a New Provider

To add a new LLM (e.g. Gemini, OpenAI, Anthropic):

1. Create `app/providers/llm/gemini.py`
2. Implement `LLMProvider` — define `summarize()` and `provider_name`
3. Update `api/deps.py` to return it when the relevant API key is set
4. No other files change

```python
# app/providers/llm/gemini.py
class GeminiLLMProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "gemini"

    async def summarize(self, reviews: list[str]) -> SummaryResult:
        # ... Gemini API call
        ...
```

This is the Open/Closed Principle in practice: the system is open for
extension (new file) and closed for modification (no existing files change).

---

## File Structure

```
app/providers/llm/
├── base.py           ← LLMProvider ABC + SummaryResult dataclass
├── huggingface.py    ← HuggingFaceLLMProvider (production)
└── mock.py           ← MockLLMProvider (dev + tests)
```
