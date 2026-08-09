"""quality gate policy snapshots and project configuration"""
from alembic import op
import sqlalchemy as sa

revision = "20260809_0009"
down_revision = "20260809_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codepilot_quality_policies",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("codepilot_projects.project_id"), primary_key=True),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("codepilot_quality_policies")
