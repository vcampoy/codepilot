"""Persist the workspace-scoped maximum findings per fix job."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0016"
down_revision = "20260815_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "codepilot_fix_configurations",
        sa.Column("max_findings_per_fix", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE codepilot_fix_configurations "
            "SET max_findings_per_fix = 10 WHERE max_findings_per_fix IS NULL"
        )
    )
    op.alter_column("codepilot_fix_configurations", "max_findings_per_fix", nullable=False)
    op.create_check_constraint(
        "ck_fix_max_findings_per_fix",
        "codepilot_fix_configurations",
        "max_findings_per_fix BETWEEN 1 AND 10",
    )


def downgrade() -> None:
    op.drop_constraint("ck_fix_max_findings_per_fix", "codepilot_fix_configurations", type_="check")
    op.drop_column("codepilot_fix_configurations", "max_findings_per_fix")
