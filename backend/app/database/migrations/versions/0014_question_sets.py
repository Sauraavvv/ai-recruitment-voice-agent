"""Telephonic round question sets.

- question_sets: per requirement, versioned (1, 2, …). status draft | approved; at most one
  draft per requirement. questions is a JSONB list of {id, text, type, rubric, weight}.
  source ai | manual, the AI model used, and a hash of the JD it was made from.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "question_sets",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", uuid, nullable=False),
        sa.Column("requirement_id", uuid, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("source", sa.String(16), server_default="manual", nullable=False),
        sa.Column(
            "questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.String(100), server_default="", nullable=False),
        sa.Column("jd_hash", sa.String(64), server_default="", nullable=False),
        sa.Column("created_by_id", uuid, nullable=False),
        sa.Column("approved_by_id", uuid, nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('draft', 'approved')", name=op.f("ck_question_sets_status")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_question_sets_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["requirements.id"],
            name=op.f("fk_question_sets_requirement_id_requirements"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_question_sets_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_question_sets_approved_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_sets")),
        sa.UniqueConstraint(
            "requirement_id", "version", name=op.f("uq_question_sets_requirement_id_version")
        ),
    )
    op.create_index(op.f("ix_question_sets_organization_id"), "question_sets", ["organization_id"])
    op.create_index(op.f("ix_question_sets_requirement_id"), "question_sets", ["requirement_id"])
    op.create_index(
        "uq_question_sets_one_draft",
        "question_sets",
        ["requirement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.execute(
        "CREATE TRIGGER trg_question_sets_updated_at BEFORE UPDATE ON question_sets "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_question_sets_updated_at ON question_sets")
    op.drop_table("question_sets")
