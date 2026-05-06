"""add review_sources and reviews tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum type ---
    source_type = postgresql.ENUM(
        "csv", "appstore", "google", "twitter", name="source_type"
    )
    source_type.create(op.get_bind())

    # --- review_sources ---
    op.create_table(
        "review_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "csv", "appstore", "google", "twitter",
                name="source_type",
                create_type=False,  # already created above
            ),
            nullable=False,
        ),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_review_sources_organization_id", "review_sources", ["organization_id"]
    )

    # --- reviews ---
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["review_sources.id"], ondelete="CASCADE"
        ),
        # Deduplication guard: same external review cannot appear twice per source.
        sa.UniqueConstraint("external_id", "source_id", name="uq_review_external_source"),
    )
    op.create_index("ix_reviews_organization_id", "reviews", ["organization_id"])
    op.create_index("ix_reviews_source_id", "reviews", ["source_id"])


def downgrade() -> None:
    # Drop reviews first — it has a FK pointing at review_sources.
    op.drop_table("reviews")
    op.drop_table("review_sources")

    op.execute("DROP TYPE IF EXISTS source_type")
