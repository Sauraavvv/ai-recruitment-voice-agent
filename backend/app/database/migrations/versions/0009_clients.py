"""Clients: the companies a recruiter hires for.

- clients: name, contact details, confidential flag, notes, status (active | on_hold | closed).
  Each belongs to an organization and to the account that added it; a name is unique per
  account, ignoring case.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("industry", sa.String(100), server_default="", nullable=False),
        sa.Column("city", sa.String(100), server_default="", nullable=False),
        sa.Column("website", sa.String(300), server_default="", nullable=False),
        sa.Column("contact_name", sa.String(200), server_default="", nullable=False),
        sa.Column("contact_phone", sa.String(32), server_default="", nullable=False),
        sa.Column("contact_email", sa.String(320), server_default="", nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'on_hold', 'closed')", name=op.f("ck_clients_status")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_clients_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_clients_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_index(op.f("ix_clients_organization_id"), "clients", ["organization_id"])
    op.create_index(op.f("ix_clients_created_by_id"), "clients", ["created_by_id"])
    op.create_index(
        "uq_clients_created_by_id_name",
        "clients",
        ["created_by_id", sa.text("lower(name)")],
        unique=True,
    )
    op.execute(
        "CREATE TRIGGER trg_clients_updated_at BEFORE UPDATE ON clients "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_clients_updated_at ON clients")
    op.drop_table("clients")
