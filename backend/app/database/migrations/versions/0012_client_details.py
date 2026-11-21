"""Client details, and clients belong to the company's super admins.

- clients: contact_email becomes email (the company's email); new contact_designation,
  address, state, and the logo (image bytes + type + when it changed).
- A client name is unique per organization (was per account that added it): only super
  admins add clients now and they all see the organization's clients.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("clients", "contact_email", new_column_name="email")
    for name, length in (("contact_designation", 200), ("address", 500), ("state", 100)):
        op.add_column(
            "clients",
            sa.Column(name, sa.String(length), server_default="", nullable=False),
        )
    op.add_column("clients", sa.Column("logo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "clients", sa.Column("logo_type", sa.String(32), server_default="", nullable=False)
    )
    op.add_column(
        "clients", sa.Column("logo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_index("uq_clients_created_by_id_name", table_name="clients")
    op.create_index(
        "uq_clients_organization_id_name",
        "clients",
        ["organization_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_clients_organization_id_name", table_name="clients")
    op.create_index(
        "uq_clients_created_by_id_name",
        "clients",
        ["created_by_id", sa.text("lower(name)")],
        unique=True,
    )
    for name in ("logo_updated_at", "logo_type", "logo", "state", "address", "contact_designation"):
        op.drop_column("clients", name)
    op.alter_column("clients", "email", new_column_name="contact_email")
