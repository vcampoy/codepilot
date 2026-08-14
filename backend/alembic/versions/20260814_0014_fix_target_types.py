"""Generalize fix jobs to findings and hotspots and split repair rules."""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0014"
down_revision = "20260813_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("codepilot_fix_configurations", sa.Column("finding_rules", sa.Text(), nullable=True))
    op.add_column("codepilot_fix_configurations", sa.Column("hotspot_rules", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE codepilot_fix_configurations SET finding_rules = rules, hotspot_rules = ''"
        )
    )
    op.alter_column("codepilot_fix_configurations", "finding_rules", nullable=False)
    op.alter_column("codepilot_fix_configurations", "hotspot_rules", nullable=False)
    op.add_column(
        "codepilot_fix_jobs",
        sa.Column("target_type", sa.String(length=16), nullable=True),
    )
    op.add_column("codepilot_fix_jobs", sa.Column("target_ids", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE codepilot_fix_jobs SET target_type = 'finding', target_ids = finding_ids"
        )
    )
    op.alter_column("codepilot_fix_jobs", "target_type", nullable=False)
    op.alter_column("codepilot_fix_jobs", "target_ids", nullable=False)


def downgrade() -> None:
    op.drop_column("codepilot_fix_jobs", "target_ids")
    op.drop_column("codepilot_fix_jobs", "target_type")
    op.drop_column("codepilot_fix_configurations", "hotspot_rules")
    op.drop_column("codepilot_fix_configurations", "finding_rules")
