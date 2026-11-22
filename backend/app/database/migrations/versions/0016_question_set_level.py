"""How hard a question set's questions are (easy | medium | hard).

The recruiter picks the level when the AI writes the questions; the AI evaluation scores the
answers against it (easy: an HR screening round, scored more gently). Null for sets made
before this, or written by hand from scratch.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("question_sets", sa.Column("level", sa.String(8), nullable=True))
    op.create_check_constraint(
        op.f("ck_question_sets_level"),
        "question_sets",
        "level IS NULL OR level IN ('easy', 'medium', 'hard')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_question_sets_level"), "question_sets", type_="check")
    op.drop_column("question_sets", "level")
