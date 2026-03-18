from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Typed base for all repositories.
    Subclasses receive the session via constructor — never via global state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
