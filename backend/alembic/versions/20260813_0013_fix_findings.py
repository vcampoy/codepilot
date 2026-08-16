"""Add Fix Findings configuration and job persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260813_0013"
down_revision = "20260811_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "codepilot_fix_configurations",
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "codepilot_fix_jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("finding_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("branch_name", sa.String(length=128), nullable=True),
        sa.Column("pull_request_url", sa.String(length=2048), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["codepilot_analyses.analysis_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_codepilot_fix_jobs_workspace", "codepilot_fix_jobs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_codepilot_fix_jobs_workspace", table_name="codepilot_fix_jobs")
    op.drop_table("codepilot_fix_jobs")
    op.drop_table("codepilot_fix_configurations")
