"""workspace scoped encrypted LLM provider configuration"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0010"
down_revision = "20260809_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codepilot_llm_configurations",
        sa.Column("workspace_id", sa.String(length=64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("codepilot_llm_configurations")
