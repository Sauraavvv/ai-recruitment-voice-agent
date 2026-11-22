"""Telephonic round calls (phase-11 step 6b).

- call_attempts.purpose: screening | telephonic (existing rows: screening).
- call_attempts.question_set_id (FK question_sets): the approved set a telephonic call asks,
  pinned when the call is queued. Required for telephonic calls (CHECK).

Downgrading refuses while telephonic attempts exist (their purpose would be lost).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_attempts",
        sa.Column("purpose", sa.String(16), server_default="screening", nullable=False),
    )
    op.add_column(
        "call_attempts",
        sa.Column("question_set_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_call_attempts_question_set_id_question_sets"),
        "call_attempts",
        "question_sets",
        ["question_set_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_call_attempts_question_set_id"), "call_attempts", ["question_set_id"])
    op.create_check_constraint(
        op.f("ck_call_attempts_purpose"),
        "call_attempts",
        "purpose IN ('screening', 'telephonic')",
    )
    op.create_check_constraint(
        op.f("ck_call_attempts_telephonic_question_set"),
        "call_attempts",
        "purpose <> 'telephonic' OR question_set_id IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM call_attempts WHERE purpose = 'telephonic') THEN
                RAISE EXCEPTION 'telephonic call attempts exist; remove them before downgrading';
            END IF;
        END $$
        """
    )
    op.drop_constraint(
        op.f("ck_call_attempts_telephonic_question_set"), "call_attempts", type_="check"
    )
    op.drop_constraint(op.f("ck_call_attempts_purpose"), "call_attempts", type_="check")
    op.drop_index(op.f("ix_call_attempts_question_set_id"), table_name="call_attempts")
    op.drop_constraint(
        op.f("fk_call_attempts_question_set_id_question_sets"), "call_attempts", type_="foreignkey"
    )
    op.drop_column("call_attempts", "question_set_id")
    op.drop_column("call_attempts", "purpose")
