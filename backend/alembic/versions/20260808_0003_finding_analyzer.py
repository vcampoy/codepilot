"""Persist analyzer identity for findings."""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
revision = "20260808_0003"
down_revision: str | None = "20260805_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("codepilot_analysis_findings", sa.Column("analyzer", sa.String(length=256), nullable=True))
    op.execute("UPDATE codepilot_analysis_findings SET analyzer = 'unknown' WHERE analyzer IS NULL")
    op.alter_column("codepilot_analysis_findings", "analyzer", nullable=False, server_default="unknown")

def downgrade() -> None:
    op.drop_column("codepilot_analysis_findings", "analyzer")
