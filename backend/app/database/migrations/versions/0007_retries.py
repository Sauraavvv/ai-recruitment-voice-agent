"""Automatic retries (phase-09).

- call_attempts.retry_decision / retry_note / retry_evaluated_at: what the retry rules decided
  when the attempt ended; set once, which makes the evaluation idempotent.
- Attempts that ended before this migration are marked as evaluated ("before_phase_9"), so the
  retry reconciler never schedules retries for old test calls.
- An index for the dispatcher's query (scheduled attempts by next_retry_at).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_attempts", sa.Column("retry_decision", sa.String(48), nullable=True))
    op.add_column("call_attempts", sa.Column("retry_note", sa.Text(), nullable=True))
    op.add_column(
        "call_attempts",
        sa.Column("retry_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE call_attempts SET retry_decision = 'before_phase_9', retry_evaluated_at = now() "
        "WHERE call_status IN ('completed', 'failed', 'no_answer', 'busy', 'cancelled', "
        "'exhausted')"
    )
    op.create_index(
        "ix_call_attempts_due",
        "call_attempts",
        ["next_retry_at"],
        postgresql_where=sa.text("call_status IN ('retry_scheduled', 'callback_requested')"),
    )


def downgrade() -> None:
    op.drop_index("ix_call_attempts_due", table_name="call_attempts")
    op.drop_column("call_attempts", "retry_evaluated_at")
    op.drop_column("call_attempts", "retry_decision")
    op.drop_column("call_attempts", "retry_note")
