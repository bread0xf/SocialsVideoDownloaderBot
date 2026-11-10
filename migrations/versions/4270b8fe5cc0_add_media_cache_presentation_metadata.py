"""add media cache presentation metadata

Revision ID: 4270b8fe5cc0
Revises: 71cd52ac280f
Create Date: 2026-11-10 20:25:48.742938

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4270b8fe5cc0"
down_revision: str | None = "71cd52ac280f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_cache", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("media_cache", sa.Column("uploader", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_cache", "uploader")
    op.drop_column("media_cache", "title")
