"""Candidates and imports for a requirement (screening calls per opening).

- candidates.requirement_id and import_batches.requirement_id (FK requirements). A row belongs to
  either a job (the original single-job flow) or a requirement: exactly one of the two is set.
- Phone uniqueness: job candidates keep one row per phone across all jobs (Phase 1 rule); a
  requirement has one row per phone, so the same person can be screened for several openings.

Downgrading refuses (NOT NULL fails) while requirement candidates or imports exist.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ONE_PARENT = "(job_id IS NULL) <> (requirement_id IS NULL)"


def upgrade() -> None:
    for table in ("candidates", "import_batches"):
        op.add_column(
            table, sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_requirement_id_requirements"),
            table,
            "requirements",
            ["requirement_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_requirement_id"), table, ["requirement_id"])
        op.alter_column(table, "job_id", nullable=True)
        op.create_check_constraint(op.f(f"ck_{table}_one_parent"), table, ONE_PARENT)

    op.drop_index("uq_candidates_phone", table_name="candidates")
    op.create_index(
        "uq_candidates_phone",
        "candidates",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("requirement_id IS NULL"),
    )
    op.create_index(
        "uq_candidates_requirement_id_phone",
        "candidates",
        ["requirement_id", "phone"],
        unique=True,
        postgresql_where=sa.text("requirement_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_candidates_requirement_id_phone", table_name="candidates")
    op.drop_index("uq_candidates_phone", table_name="candidates")
    op.create_index("uq_candidates_phone", "candidates", ["phone"], unique=True)
    for table in ("candidates", "import_batches"):
        op.drop_constraint(op.f(f"ck_{table}_one_parent"), table, type_="check")
        op.alter_column(table, "job_id", nullable=False)
        op.drop_index(op.f(f"ix_{table}_requirement_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_requirement_id_requirements"), table, type_="foreignkey"
        )
        op.drop_column(table, "requirement_id")
