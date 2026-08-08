"""Persist deterministic per-file analysis insights."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0006"
down_revision: str | None = "20260808_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "codepilot_analysis_file_insights",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("hotspot_score", sa.Float(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("risk", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["codepilot_analyses.analysis_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("analysis_id", "path", name="uq_analysis_file_insight_path"),
    )


def downgrade() -> None:
    op.drop_table("codepilot_analysis_file_insights")
