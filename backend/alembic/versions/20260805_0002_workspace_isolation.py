"""Add tenant workspace ownership to analysis records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0002"
down_revision: str | None = "20260805_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "codepilot_analyses",
        sa.Column("workspace_id", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.create_index(
        "ix_codepilot_analyses_workspace_id",
        "codepilot_analyses",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_codepilot_analyses_workspace_id", table_name="codepilot_analyses")
    op.drop_column("codepilot_analyses", "workspace_id")
