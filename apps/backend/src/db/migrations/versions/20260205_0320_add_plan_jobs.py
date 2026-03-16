from __future__ import annotations

"""add_plan_jobs

Revision ID: add_plan_jobs
Revises: add_sealed_at
Create Date: 2026-02-05 03:20:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_plan_jobs"
down_revision = "add_sealed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Criar enum JobStatus
    job_status_enum = postgresql.ENUM(
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "TIMEBOXED",
        name="jobstatus",
        create_type=False,
    )
    job_status_enum.create(op.get_bind(), checkfirst=True)

    # Criar tabela plan_jobs
    op.create_table(
        "plan_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("plan_params", postgresql.JSONB, nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", job_status_enum, nullable=False, server_default="QUEUED"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_hash", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("duration_ms", sa.String(20), nullable=True),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.snapshot_id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"]),
    )

    # Criar índices
    op.create_index("ix_plan_jobs_snapshot_id", "plan_jobs", ["snapshot_id"])
    op.create_index("ix_plan_jobs_snapshot_hash", "plan_jobs", ["snapshot_hash"])
    op.create_index("ix_plan_jobs_correlation_id", "plan_jobs", ["correlation_id"])
    op.create_index("ix_plan_jobs_status", "plan_jobs", ["status"])
    op.create_index("ix_plan_jobs_created_at", "plan_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_plan_jobs_created_at", table_name="plan_jobs")
    op.drop_index("ix_plan_jobs_status", table_name="plan_jobs")
    op.drop_index("ix_plan_jobs_correlation_id", table_name="plan_jobs")
    op.drop_index("ix_plan_jobs_snapshot_hash", table_name="plan_jobs")
    op.drop_index("ix_plan_jobs_snapshot_id", table_name="plan_jobs")
    op.drop_table("plan_jobs")
    op.execute("DROP TYPE IF EXISTS jobstatus")
