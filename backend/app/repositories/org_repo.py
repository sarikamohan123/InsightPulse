from sqlalchemy import select

from app.models.organization import Organization, OrgPlan
from app.repositories.base import BaseRepository


class OrgRepository(BaseRepository[Organization]):

    async def create(self, name: str, slug: str) -> Organization:
        org = Organization(name=name, slug=slug, plan=OrgPlan.free)
        self.session.add(org)
        await self.session.flush()
        await self.session.refresh(org)
        return org

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        return result.scalar_one_or_none()
