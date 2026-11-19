"""Finalization and the Google Sheets outbox (phase-07 §5, P7-T9).

- conversations.finalized_at: set in the finalization transaction (idempotency check).
- sync_logs: attempts, next_attempt_at, updated_at, plus an index for the drain and reconciler.

The phase plan names this migration 0003; 0003 and 0004 were taken by then.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sync_logs",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "sync_logs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sync_logs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_sync_logs_sync_status_next_attempt_at",
        "sync_logs",
        ["sync_status", "next_attempt_at"],
    )
    op.execute(
        "CREATE TRIGGER trg_sync_logs_updated_at BEFORE UPDATE ON sync_logs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sync_logs_updated_at ON sync_logs")
    op.drop_index("ix_sync_logs_sync_status_next_attempt_at", table_name="sync_logs")
    op.drop_column("sync_logs", "updated_at")
    op.drop_column("sync_logs", "next_attempt_at")
    op.drop_column("sync_logs", "attempts")
    op.drop_column("conversations", "finalized_at")
