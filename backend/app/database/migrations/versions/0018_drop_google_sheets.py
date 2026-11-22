"""Google Sheets removed: the sync outbox (sync_logs) and the stored sheet setting go.

The database is the only record of candidates; nothing is copied to a spreadsheet any more.
The downgrade recreates an empty sync_logs table (its rows are not kept).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sync_logs_updated_at ON sync_logs")
    op.drop_table("sync_logs")
    op.execute("DELETE FROM app_settings WHERE key = 'google_sheets'")


def downgrade() -> None:
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("candidate_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("sync_status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'success', 'failed')", name=op.f("ck_sync_logs_sync_status")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_sync_logs_candidate_id_candidates"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_logs")),
    )
    op.create_index(
        "ix_sync_logs_candidate_id_created_at", "sync_logs", ["candidate_id", "created_at"]
    )
    op.create_index(
        "ix_sync_logs_sync_status_next_attempt_at", "sync_logs", ["sync_status", "next_attempt_at"]
    )
    op.execute(
        "CREATE TRIGGER trg_sync_logs_updated_at BEFORE UPDATE ON sync_logs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
