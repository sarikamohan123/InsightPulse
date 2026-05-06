import csv
import io
from datetime import date

from app.providers.sources.base import SourceProvider
from app.repositories.review_repo import ReviewRow


class CSVSourceProvider(SourceProvider):
    """
    Parses a CSV file upload into ReviewRows.

    Expected CSV columns (header row required):
        content      — required; rows without this are skipped
        external_id  — optional
        author       — optional
        rating       — optional; parsed as float, invalid values are ignored
        review_date  — optional; expected ISO format YYYY-MM-DD

    Any extra columns are captured in raw_metadata for audit purposes.
    """

    async def ingest(self, file_bytes: bytes | None) -> list[ReviewRow]:
        if not file_bytes:
            return []

        # Decode bytes → string. UTF-8 with fallback to latin-1 covers most CSVs.
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))
        rows: list[ReviewRow] = []

        for raw_row in reader:
            content = (raw_row.get("content") or "").strip()
            if not content:
                # Rows without content are silently skipped here.
                # They will be counted as skipped_count in the ingest response.
                continue

            rows.append(
                ReviewRow(
                    content=content,
                    external_id=self._str(raw_row.get("external_id")),
                    author=self._str(raw_row.get("author")),
                    rating=self._float(raw_row.get("rating")),
                    review_date=self._date(raw_row.get("review_date")),
                    raw_metadata=dict(raw_row),  # full original row preserved
                )
            )

        return rows

    # --- Private helpers ---

    @staticmethod
    def _str(value: str | None) -> str | None:
        v = (value or "").strip()
        return v if v else None

    @staticmethod
    def _float(value: str | None) -> float | None:
        try:
            return float(value) if value and value.strip() else None
        except ValueError:
            return None

    @staticmethod
    def _date(value: str | None) -> date | None:
        try:
            return date.fromisoformat(value.strip()) if value and value.strip() else None
        except ValueError:
            return None
