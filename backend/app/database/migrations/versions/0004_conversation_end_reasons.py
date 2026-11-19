"""Conversation end reasons on call_attempts.end_reason (phase-06 §5.6).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

P5_REASONS = (
    "'no_answer', 'busy', 'invalid_number', 'candidate_hangup', 'agent_completed', "
    "'provider_failed', 'technical_failure', 'cancelled'"
)
P6_REASONS = (
    P5_REASONS + ", 'declined', 'opted_out', 'callback_scheduled', 'wrong_person', "
    "'silence_timeout', 'max_duration', 'escalated'"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_call_attempts_end_reason"), "call_attempts", type_="check")
    op.create_check_constraint(
        op.f("ck_call_attempts_end_reason"), "call_attempts", f"end_reason IN ({P6_REASONS})"
    )


def downgrade() -> None:
    # Phase 6 reasons fold back into the closest Phase 5 value
    op.execute(
        "UPDATE call_attempts SET end_reason = 'agent_completed' WHERE end_reason IN "
        "('declined', 'opted_out', 'callback_scheduled', 'wrong_person', 'escalated', "
        "'max_duration')"
    )
    op.execute(
        "UPDATE call_attempts SET end_reason = 'candidate_hangup' "
        "WHERE end_reason = 'silence_timeout'"
    )
    op.drop_constraint(op.f("ck_call_attempts_end_reason"), "call_attempts", type_="check")
    op.create_check_constraint(
        op.f("ck_call_attempts_end_reason"), "call_attempts", f"end_reason IN ({P5_REASONS})"
    )
