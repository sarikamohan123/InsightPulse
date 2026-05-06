import uuid
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.providers.sources.csv_provider import CSVSourceProvider
from app.repositories.org_repo import OrgRepository
from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.review_repo import ReviewRepository
from app.repositories.review_source_repo import ReviewSourceRepository
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService
from app.services.review_service import ReviewService

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.")

    try:
        payload = decode_token(credentials.credentials, settings)
    except JWTError:
        raise UnauthorizedError("Invalid or expired token.")

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type.")

    user = await UserRepository(session).get_by_pk(uuid.UUID(payload["sub"]))
    if not user:
        raise UnauthorizedError("User not found.")
    if str(user.organization_id) != payload.get("org_id"):
        raise UnauthorizedError("Token organisation mismatch.")
    if not user.is_active:
        raise ForbiddenError("Account is deactivated.")

    return user


async def get_organization_id(
    current_user: User = Depends(get_current_user),
) -> UUID:
    return current_user.organization_id


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.admin:
        raise ForbiddenError("Admin role required.")
    return current_user


def get_auth_service(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(
        org_repo=OrgRepository(session),
        user_repo=UserRepository(session),
        token_repo=RefreshTokenRepository(session),
        settings=settings,
    )


def get_review_service(
    session: AsyncSession = Depends(get_db),
) -> ReviewService:
    return ReviewService(
        source_repo=ReviewSourceRepository(session),
        review_repo=ReviewRepository(session),
        source_provider=CSVSourceProvider(),
    )
