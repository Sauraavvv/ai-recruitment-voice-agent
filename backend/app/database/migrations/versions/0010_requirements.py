"""Requirements: the openings at a client.

- requirements: client_id, title, location, work_mode, openings, experience and CTC ranges,
  notice limit, skills and must-haves (JSONB lists), job description, deadline, notes, status
  (open | on_hold | filled | closed).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "requirements",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", uuid, nullable=False),
        sa.Column("client_id", uuid, nullable=False),
        sa.Column("created_by_id", uuid, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), server_default="", nullable=False),
        sa.Column("work_mode", sa.String(16), server_default="", nullable=False),
        sa.Column("openings", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("experience_min", sa.Numeric(4, 1), nullable=True),
        sa.Column("experience_max", sa.Numeric(4, 1), nullable=True),
        sa.Column("ctc_min", sa.Numeric(6, 2), nullable=True),
        sa.Column("ctc_max", sa.Numeric(6, 2), nullable=True),
        sa.Column("notice_max_days", sa.Integer(), nullable=True),
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "must_haves",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("job_description", sa.Text(), server_default="", nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('open', 'on_hold', 'filled', 'closed')",
            name=op.f("ck_requirements_status"),
        ),
        sa.CheckConstraint(
            "work_mode IN ('', 'onsite', 'hybrid', 'remote')",
            name=op.f("ck_requirements_work_mode"),
        ),
        sa.CheckConstraint("openings >= 1", name=op.f("ck_requirements_openings_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_requirements_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_requirements_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_requirements_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirements")),
    )
    for column in ("organization_id", "client_id", "created_by_id"):
        op.create_index(op.f(f"ix_requirements_{column}"), "requirements", [column])
    op.execute(
        "CREATE TRIGGER trg_requirements_updated_at BEFORE UPDATE ON requirements "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_requirements_updated_at ON requirements")
    op.drop_table("requirements")
