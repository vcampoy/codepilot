"""Persist bounded source context alongside findings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("codepilot_analysis_findings", sa.Column("source_context", sa.JSON()))


def downgrade() -> None:
    op.drop_column("codepilot_analysis_findings", "source_context")
