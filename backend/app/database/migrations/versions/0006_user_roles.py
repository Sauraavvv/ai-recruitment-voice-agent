"""User roles (phase-08: only an admin may change the Google Sheet).

- users.role: admin | recruiter (CHECK). Existing accounts become admin: until now every account
  was created by the operator with `make create-user`; new accounts default to recruiter.

The phase plan's 0004_app_settings is not needed: app_settings (0003, key/value JSONB) already
holds the settings sections.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(16), server_default=sa.text("'recruiter'"), nullable=False),
    )
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'recruiter')")
    op.execute("UPDATE users SET role = 'admin'")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.drop_column("users", "role")
