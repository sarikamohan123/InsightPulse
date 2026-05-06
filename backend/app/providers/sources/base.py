from abc import ABC, abstractmethod

from app.repositories.review_repo import ReviewRow


class SourceProvider(ABC):
    """
    Abstract base for all review source providers.

    Every source type (CSV, App Store, Google, Twitter) implements this interface.
    The ReviewService depends only on this ABC — never on a concrete class.
    This is the Dependency Inversion Principle in practice: high-level policy
    (the service) does not depend on low-level detail (CSV parsing logic).

    To add a new source type in Phase 6:
    1. Create a new file e.g. providers/sources/appstore_provider.py
    2. Subclass SourceProvider and implement ingest()
    3. Wire it in api/deps.py based on the source's source_type
    No existing code changes required.
    """

    @abstractmethod
    async def ingest(self, file_bytes: bytes | None) -> list[ReviewRow]:
        """
        Parse raw source data and return a list of ReviewRows.

        Args:
            file_bytes: Raw bytes from the uploaded file (CSV), or None for
                        simulated sources that generate their own data.

        Returns:
            A list of ReviewRow objects. Rows with empty content should be
            excluded by the provider — the repo will skip any that slip through.
        """
        ...
