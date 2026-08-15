"""Persist the branch selected for each repository analysis."""

import sqlalchemy as sa
from alembic import op

revision = "20260815_0015"
down_revision = "20260814_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "codepilot_analyses",
        sa.Column("branch_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("codepilot_analyses", "branch_name")
