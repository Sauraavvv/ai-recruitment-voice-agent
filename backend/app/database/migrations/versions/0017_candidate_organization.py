"""Every candidate belongs to an organization (company), so no company sees another's.

- candidates.organization_id (NOT NULL, FK organizations, indexed).
  - A requirement's candidates: the requirement's organization.
  - Candidates of the original job flow (no requirement): the oldest organization, the one the
    data belonged to before sign-up made several possible (migration 0008). One is created
    if there are such candidates and no organization at all.
- The original flow's "one phone number once" rule becomes per organization: another company
  can have the same number (and is never told this one exists).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        """
        UPDATE candidates c SET organization_id = r.organization_id
        FROM requirements r WHERE r.id = c.requirement_id
        """
    )
    op.execute(
        """
        INSERT INTO organizations (name)
        SELECT 'My organization'
        WHERE EXISTS (SELECT 1 FROM candidates WHERE organization_id IS NULL)
          AND NOT EXISTS (SELECT 1 FROM organizations)
        """
    )
    op.execute(
        """
        UPDATE candidates SET organization_id =
            (SELECT id FROM organizations ORDER BY created_at, id LIMIT 1)
        WHERE organization_id IS NULL
        """
    )
    op.alter_column("candidates", "organization_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_candidates_organization_id_organizations"),
        "candidates",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_candidates_organization_id"), "candidates", ["organization_id"])
    op.drop_index("uq_candidates_phone", table_name="candidates")
    op.create_index(
        "uq_candidates_organization_id_phone",
        "candidates",
        ["organization_id", "phone"],
        unique=True,
        postgresql_where=sa.text("requirement_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_candidates_organization_id_phone", table_name="candidates")
    op.create_index(
        "uq_candidates_phone",
        "candidates",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("requirement_id IS NULL"),
    )
    op.drop_index(op.f("ix_candidates_organization_id"), table_name="candidates")
    op.drop_constraint(
        op.f("fk_candidates_organization_id_organizations"), "candidates", type_="foreignkey"
    )
    op.drop_column("candidates", "organization_id")
