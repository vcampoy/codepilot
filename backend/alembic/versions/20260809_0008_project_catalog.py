"""Persist project catalog and link analyses."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0008"
down_revision: str | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "codepilot_projects",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("repository_url", sa.String(length=2048), nullable=False),
        sa.Column("repository_key", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("workspace_id", "repository_key", name="uq_codepilot_project_identity"),
    )
    op.add_column("codepilot_analyses", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_analysis_project", "codepilot_analyses", "codepilot_projects", ["project_id"], ["project_id"])
    bind = op.get_bind()
    project_rows_query = (
        "SELECT workspace_id, min(repository_url) AS repository_url, "
        "min(created_at) AS created_at, max(created_at) AS updated_at "
        "FROM codepilot_analyses GROUP BY workspace_id, "
        "lower(regexp_replace(regexp_replace(repository_url, '/$', ''), '\\.git$', ''))"
    )
    rows = bind.execute(sa.text(project_rows_query)).mappings()
    for row in rows:
        url = str(row["repository_url"])
        key = url.strip().lower().rstrip("/").removesuffix(".git")
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or url
        project_id = uuid4()
        bind.execute(sa.text("INSERT INTO codepilot_projects (project_id, workspace_id, repository_url, repository_key, name, created_at, updated_at) VALUES (:id, :workspace, :url, :key, :name, :created, :updated)"), {"id": project_id, "workspace": row["workspace_id"], "url": url, "key": key, "name": name, "created": row["created_at"], "updated": row["updated_at"]})
        analysis_update_query = (
            "UPDATE codepilot_analyses SET project_id = :id "
            "WHERE workspace_id = :workspace AND "
            "lower(regexp_replace(regexp_replace(repository_url, '/$', ''), '\\.git$', '')) = :key"
        )
        bind.execute(
            sa.text(analysis_update_query),
            {"id": project_id, "workspace": row["workspace_id"], "key": key},
        )


def downgrade() -> None:
    op.drop_constraint("fk_analysis_project", "codepilot_analyses", type_="foreignkey")
    op.drop_column("codepilot_analyses", "project_id")
    op.drop_table("codepilot_projects")
