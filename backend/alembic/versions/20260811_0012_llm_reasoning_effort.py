"""persist selected reasoning effort for LLM configuration"""

import sqlalchemy as sa
from alembic import op

revision = "20260811_0012"
down_revision = "20260810_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "codepilot_llm_configurations",
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("codepilot_llm_configurations", "reasoning_effort")
