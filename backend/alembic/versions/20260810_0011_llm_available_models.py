"""persist discovered model catalogs"""

import sqlalchemy as sa
from alembic import op

revision = "20260810_0011"
down_revision = "20260809_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "codepilot_llm_configurations", sa.Column("available_models", sa.JSON(), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE codepilot_llm_configurations "
            "SET available_models = json_build_array(model) "
            "WHERE available_models IS NULL"
        )
    )
    op.alter_column(
        "codepilot_llm_configurations",
        "available_models",
        nullable=False,
        server_default=sa.text("'[]'::json"),
    )


def downgrade() -> None:
    op.drop_column("codepilot_llm_configurations", "available_models")
