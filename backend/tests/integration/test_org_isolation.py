"""
Integration tests: org isolation at the repository layer.

These tests call repositories directly — no HTTP — because isolation is
enforced at the repo layer and should be verified there.

Every new repo method added in Phase 3+ that returns tenant data must get
a corresponding test here proving Org B cannot see Org A's records.
"""

from app.models.review_source import SourceType
from app.models.user import UserRole
from app.repositories.review_repo import ReviewRow, ReviewRepository
from app.repositories.review_source_repo import ReviewSourceRepository
from app.repositories.user_repo import UserRepository


# ---------------------------------------------------------------------------
# UserRepository isolation
# ---------------------------------------------------------------------------

async def test_list_all_returns_only_own_org_users(test_db, org_factory):
    org_a = await org_factory("Org Alpha")
    org_b = await org_factory("Org Beta")

    repo = UserRepository(test_db)
    await repo.create(
        organization_id=org_a.id,
        email="alice@alpha.com",
        hashed_password="hashed",
        role=UserRole.admin,
    )
    await repo.create(
        organization_id=org_b.id,
        email="bob@beta.com",
        hashed_password="hashed",
        role=UserRole.admin,
    )

    org_a_users = await repo.list_all(organization_id=org_a.id)

    assert len(org_a_users) == 1
    assert org_a_users[0].email == "alice@alpha.com"


async def test_get_by_id_returns_none_for_other_org_user(test_db, org_factory):
    org_a = await org_factory("Org Alpha")
    org_b = await org_factory("Org Beta")

    repo = UserRepository(test_db)
    user_a = await repo.create(
        organization_id=org_a.id,
        email="alice@alpha.com",
        hashed_password="hashed",
        role=UserRole.admin,
    )

    # Attempt to fetch org_a's user using org_b's id — must return None
    result = await repo.get_by_id(id=user_a.id, organization_id=org_b.id)

    assert result is None


# ---------------------------------------------------------------------------
# ReviewSourceRepository isolation
# ---------------------------------------------------------------------------

async def test_list_sources_returns_only_own_org(test_db, org_factory):
    org_a = await org_factory("Source Org A")
    org_b = await org_factory("Source Org B")

    repo = ReviewSourceRepository(test_db)
    await repo.create(
        organization_id=org_a.id,
        name="Org A Source",
        source_type=SourceType.csv,
        config={},
    )
    await repo.create(
        organization_id=org_b.id,
        name="Org B Source",
        source_type=SourceType.csv,
        config={},
    )

    org_a_sources = await repo.list_all(organization_id=org_a.id)

    assert len(org_a_sources) == 1
    assert org_a_sources[0].name == "Org A Source"


async def test_get_source_by_id_returns_none_for_other_org(test_db, org_factory):
    org_a = await org_factory("Source Org A2")
    org_b = await org_factory("Source Org B2")

    repo = ReviewSourceRepository(test_db)
    source_a = await repo.create(
        organization_id=org_a.id,
        name="Org A Source",
        source_type=SourceType.csv,
        config={},
    )

    # Org B tries to access Org A's source — must return None.
    result = await repo.get_by_id(id=source_a.id, organization_id=org_b.id)

    assert result is None


# ---------------------------------------------------------------------------
# ReviewRepository isolation
# ---------------------------------------------------------------------------

async def test_list_reviews_returns_only_own_org(test_db, org_factory):
    org_a = await org_factory("Review Org A")
    org_b = await org_factory("Review Org B")

    source_repo = ReviewSourceRepository(test_db)
    review_repo = ReviewRepository(test_db)

    source_a = await source_repo.create(
        organization_id=org_a.id,
        name="Source A",
        source_type=SourceType.csv,
        config={},
    )
    source_b = await source_repo.create(
        organization_id=org_b.id,
        name="Source B",
        source_type=SourceType.csv,
        config={},
    )

    await review_repo.create_bulk(
        organization_id=org_a.id,
        source_id=source_a.id,
        rows=[ReviewRow(content="Org A review", external_id="a1")],
    )
    await review_repo.create_bulk(
        organization_id=org_b.id,
        source_id=source_b.id,
        rows=[ReviewRow(content="Org B review", external_id="b1")],
    )

    # Org A queries its own source — must see only its own review.
    total, items = await review_repo.list_by_source(
        organization_id=org_a.id,
        source_id=source_a.id,
    )

    assert total == 1
    assert items[0].content == "Org A review"


async def test_get_review_by_id_returns_none_for_other_org(test_db, org_factory):
    org_a = await org_factory("Review Org A2")
    org_b = await org_factory("Review Org B2")

    source_repo = ReviewSourceRepository(test_db)
    review_repo = ReviewRepository(test_db)

    source_a = await source_repo.create(
        organization_id=org_a.id,
        name="Source A",
        source_type=SourceType.csv,
        config={},
    )
    await review_repo.create_bulk(
        organization_id=org_a.id,
        source_id=source_a.id,
        rows=[ReviewRow(content="Private review", external_id="prv-1")],
    )

    # Fetch the inserted review directly to get its id.
    _, reviews_a = await review_repo.list_by_source(
        organization_id=org_a.id, source_id=source_a.id
    )
    review_id = reviews_a[0].id

    # Org B attempts to fetch Org A's review by id — must return None.
    result = await review_repo.get_by_id(id=review_id, organization_id=org_b.id)

    assert result is None
