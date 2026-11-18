"""Telephony: call attempt provider fields, one-live-attempt guard, webhook_events.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIVE = (
    "'pending', 'queued', 'initiating', 'ringing', 'in_progress', "
    "'retry_scheduled', 'callback_requested'"
)
ATTEMPT_TYPES = "'initial', 'manual', 'retry', 'callback'"
END_REASONS = (
    "'no_answer', 'busy', 'invalid_number', 'candidate_hangup', 'agent_completed', "
    "'provider_failed', 'technical_failure', 'cancelled'"
)


def upgrade() -> None:
    op.add_column(
        "call_attempts",
        sa.Column("attempt_type", sa.String(length=16), server_default="initial", nullable=False),
    )
    op.add_column("call_attempts", sa.Column("provider_status", sa.String(length=50)))
    op.add_column("call_attempts", sa.Column("stream_id", sa.String(length=200)))
    op.add_column("call_attempts", sa.Column("end_reason", sa.String(length=32)))
    op.create_check_constraint(
        op.f("ck_call_attempts_attempt_type"), "call_attempts", f"attempt_type IN ({ATTEMPT_TYPES})"
    )
    op.create_check_constraint(
        op.f("ck_call_attempts_end_reason"), "call_attempts", f"end_reason IN ({END_REASONS})"
    )
    op.create_index(
        "uq_call_attempts_one_live",
        "call_attempts",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text(f"call_status IN ({LIVE})"),
    )
    op.create_unique_constraint(
        "uq_call_attempts_number", "call_attempts", ["candidate_id", "attempt_number"]
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_call_id", sa.String(length=200), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
    )
    op.create_index("uq_webhook_events_dedupe_key", "webhook_events", ["dedupe_key"], unique=True)
    op.create_index(
        "ix_webhook_events_provider_call_id", "webhook_events", ["provider_call_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_provider_call_id", table_name="webhook_events")
    op.drop_index("uq_webhook_events_dedupe_key", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_constraint("uq_call_attempts_number", "call_attempts", type_="unique")
    op.drop_index("uq_call_attempts_one_live", table_name="call_attempts")
    op.drop_constraint(op.f("ck_call_attempts_end_reason"), "call_attempts", type_="check")
    op.drop_constraint(op.f("ck_call_attempts_attempt_type"), "call_attempts", type_="check")
    op.drop_column("call_attempts", "end_reason")
    op.drop_column("call_attempts", "stream_id")
    op.drop_column("call_attempts", "provider_status")
    op.drop_column("call_attempts", "attempt_type")
