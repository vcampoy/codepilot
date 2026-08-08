"""Persist optional finding title, evidence, and remediation details."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0005"
down_revision: str | None = "20260808_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("codepilot_analysis_findings", sa.Column("title", sa.String(length=512)))
    op.add_column("codepilot_analysis_findings", sa.Column("evidence", sa.Text()))
    op.add_column("codepilot_analysis_findings", sa.Column("remediation", sa.Text()))
    op.execute(
        "UPDATE codepilot_analysis_findings SET title = rule_id WHERE title IS NULL"
    )


def downgrade() -> None:
    op.drop_column("codepilot_analysis_findings", "remediation")
    op.drop_column("codepilot_analysis_findings", "evidence")
    op.drop_column("codepilot_analysis_findings", "title")
