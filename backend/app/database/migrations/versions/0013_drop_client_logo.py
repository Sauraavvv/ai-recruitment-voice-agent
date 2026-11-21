"""Drop the client logo (the user decided against it).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("logo_updated_at", "logo_type", "logo"):
        op.drop_column("clients", name)


def downgrade() -> None:
    op.add_column("clients", sa.Column("logo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "clients", sa.Column("logo_type", sa.String(32), server_default="", nullable=False)
    )
    op.add_column(
        "clients", sa.Column("logo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
