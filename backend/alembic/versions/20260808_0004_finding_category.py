"""Persist normalized finding categories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0004"
down_revision: str | None = "20260808_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "codepilot_analysis_findings",
        sa.Column("category", sa.String(length=64), nullable=False, server_default="other"),
    )
    op.alter_column("codepilot_analysis_findings", "category", server_default=None)


def downgrade() -> None:
    op.drop_column("codepilot_analysis_findings", "category")
