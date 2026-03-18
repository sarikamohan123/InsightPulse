import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
import app.models  # noqa: F401 — registers all models with Base.metadata

settings = get_settings()

_test_engine = create_async_engine(settings.test_database_url)

# ---------------------------------------------------------------------------
# Session-scoped: create tables once before all tests, drop after all tests.
# Using a sync fixture with asyncio.run() avoids event-loop-scope conflicts
# with pytest-asyncio.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def create_tables():
    async def _up():
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def _down():
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await _test_engine.dispose()

    asyncio.run(_up())
    yield
    asyncio.run(_down())


# ---------------------------------------------------------------------------
# Function-scoped: each test runs inside a transaction that is rolled back,
# so no data leaks between tests.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_db():
    async with _test_engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(conn, expire_on_commit=False) as session:
            yield session
        await conn.rollback()


# ---------------------------------------------------------------------------
# HTTP client wired to the test session.
# get_db is overridden so every request in a test uses the same transaction.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(test_db):
    async def _override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Pre-authenticated headers. Registers a user and logs in, returns the
# Authorization header dict ready for use in tests.
# ---------------------------------------------------------------------------

_TEST_EMAIL = "alice@example.com"
_TEST_PASSWORD = "securepass123"
_TEST_ORG = "Acme Corp"


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": _TEST_EMAIL,
            "password": _TEST_PASSWORD,
            "organization_name": _TEST_ORG,
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Factory for creating extra organisations directly in the test DB.
# Used in multi-tenancy isolation tests (Phase 2).
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def org_factory(test_db):
    import re
    from app.models.organization import Organization, OrgPlan

    async def _create(name: str) -> Organization:
        slug = re.sub(r"[\s_]+", "-", name.lower().strip())
        org = Organization(name=name, slug=slug, plan=OrgPlan.free)
        test_db.add(org)
        await test_db.flush()
        await test_db.refresh(org)
        return org

    return _create


# ---------------------------------------------------------------------------
# Placeholder — replaced with real MockLLMProvider in Phase 4.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_llm_provider():
    return None
