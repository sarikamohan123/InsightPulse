"""
Integration tests: org isolation at the repository layer.

These tests call repositories directly — no HTTP — because isolation is
enforced at the repo layer and should be verified there.

Every new repo method added in Phase 3+ that returns tenant data must get
a corresponding test here proving Org B cannot see Org A's records.
"""

import uuid

import pytest

from app.models.user import UserRole
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
