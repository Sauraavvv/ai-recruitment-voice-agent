"""Default screening questions per company: one company's edits never change another's calls.

The one shared list (app_settings key "default_questions") becomes the oldest organization's
("default_questions:<its id>"): the company that edited it before sign-up made several
possible, and the owner of the original flow's data (migration 0017). Every other company
starts from the ten originals. With no organization at all, the shared list is dropped.
The downgrade makes the oldest organization's list the shared one again and drops the others.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE app_settings SET key = 'default_questions:' || "
        "(SELECT id FROM organizations ORDER BY created_at, id LIMIT 1)::text "
        "WHERE key = 'default_questions' AND EXISTS (SELECT 1 FROM organizations)"
    )
    op.execute("DELETE FROM app_settings WHERE key = 'default_questions'")


def downgrade() -> None:
    op.execute(
        "UPDATE app_settings SET key = 'default_questions' "
        "WHERE key = 'default_questions:' || "
        "(SELECT id FROM organizations ORDER BY created_at, id LIMIT 1)::text"
    )
    op.execute("DELETE FROM app_settings WHERE key LIKE 'default\\_questions:%'")
