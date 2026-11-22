"""Organizations and sign-up.

- organizations: a company (HR firm) using CallZest; sign-up creates one with its super admin.
- users.organization_id (NOT NULL). Accounts that exist before this migration are put in one
  organization named after the Settings page's organization name (or "My organization").
- users.role: admin becomes super_admin; roles are now super_admin | recruiter.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.add_column(
        "users", sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    # Existing accounts: one organization, only when there are accounts to put in it
    op.execute(
        """
        INSERT INTO organizations (name)
        SELECT COALESCE(
            NULLIF(TRIM((SELECT value->>'organization_name' FROM app_settings
                         WHERE key = 'general')), ''),
            'My organization')
        WHERE EXISTS (SELECT 1 FROM users)
        """
    )
    op.execute("UPDATE users SET organization_id = (SELECT id FROM organizations LIMIT 1)")
    op.alter_column("users", "organization_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_users_organization_id_organizations"),
        "users",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"])

    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.execute("UPDATE users SET role = 'super_admin' WHERE role = 'admin'")
    op.create_check_constraint(
        op.f("ck_users_role"), "users", "role IN ('super_admin', 'recruiter')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'recruiter')")

    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_organization_id_organizations"), "users", type_="foreignkey")
    op.drop_column("users", "organization_id")
    op.drop_table("organizations")
