import hashlib
import re
import uuid
from datetime import datetime, timezone

from jose import JWTError

from app.core.config import Settings
from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.repositories.org_repo import OrgRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(
        self,
        org_repo: OrgRepository,
        user_repo: UserRepository,
        token_repo: RefreshTokenRepository,
        settings: Settings,
    ) -> None:
        self.org_repo = org_repo
        self.user_repo = user_repo
        self.token_repo = token_repo
        self.settings = settings

    async def register(
        self,
        email: str,
        password: str,
        organization_name: str,
    ) -> tuple[User, Organization]:
        if await self.user_repo.get_by_email(email):
            raise ConflictError("Email already registered.")

        org = await self.org_repo.create(
            name=organization_name,
            slug=_slugify(organization_name),
        )
        user = await self.user_repo.create(
            organization_id=org.id,
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.admin,
        )
        return user, org

    async def login(self, email: str, password: str) -> dict:
        user = await self.user_repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid credentials.")
        if not user.is_active:
            raise ForbiddenError("Account is deactivated.")

        access_token = create_access_token(
            user.id, user.organization_id, user.role, self.settings
        )
        raw_refresh = create_refresh_token(user.id, self.settings)
        payload = decode_token(raw_refresh, self.settings)
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        await self.token_repo.create(
            user_id=user.id,
            token_hash=_hash_token(raw_refresh),
            expires_at=expires_at,
        )
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }

    async def refresh(self, refresh_token: str) -> dict:
        try:
            payload = decode_token(refresh_token, self.settings)
        except JWTError:
            raise UnauthorizedError("Invalid or expired refresh token.")

        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type.")

        stored = await self.token_repo.get_by_hash(_hash_token(refresh_token))
        if not stored or stored.revoked:
            raise UnauthorizedError("Refresh token has been revoked or does not exist.")

        user = await self.user_repo.get_by_id(uuid.UUID(payload["sub"]))
        if not user or not user.is_active:
            raise UnauthorizedError("User not found or deactivated.")

        await self.token_repo.revoke(stored)

        new_access = create_access_token(
            user.id, user.organization_id, user.role, self.settings
        )
        new_refresh = create_refresh_token(user.id, self.settings)
        new_payload = decode_token(new_refresh, self.settings)
        expires_at = datetime.fromtimestamp(new_payload["exp"], tz=timezone.utc)

        await self.token_repo.create(
            user_id=user.id,
            token_hash=_hash_token(new_refresh),
            expires_at=expires_at,
        )
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }
