"""Who uploaded each candidate: a recruiter sees only their own, a super admin everyone's.

- candidates.uploaded_by_id (FK users, indexed, nullable).
- Uploaded candidates get their batch's uploader: confirming a batch stamps every candidate
  it adds with consent_at = the batch's confirmed_at, for the same job or requirement.
- Anything else (added by hand before this, seeded, test data) stays unknown (NULL): only the
  company's super admins see those.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_candidates_uploaded_by_id_users"),
        "candidates",
        "users",
        ["uploaded_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_candidates_uploaded_by_id"), "candidates", ["uploaded_by_id"])
    op.execute(
        """
        UPDATE candidates c SET uploaded_by_id = b.uploaded_by
        FROM import_batches b
        WHERE b.status = 'confirmed'
          AND b.confirmed_at = c.consent_at
          AND c.consent_source = 'recruiter_attested_import'
          AND (b.requirement_id = c.requirement_id OR b.job_id = c.job_id)
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_candidates_uploaded_by_id"), table_name="candidates")
    op.drop_constraint(op.f("fk_candidates_uploaded_by_id_users"), "candidates", type_="foreignkey")
    op.drop_column("candidates", "uploaded_by_id")
