import uuid

from sqlalchemy import select

from app.models.user import User, UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):

    async def create(
        self,
        organization_id: uuid.UUID,
        email: str,
        hashed_password: str,
        role: UserRole,
    ) -> User:
        user = User(
            organization_id=organization_id,
            email=email,
            hashed_password=hashed_password,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
