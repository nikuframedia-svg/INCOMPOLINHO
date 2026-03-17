from __future__ import annotations

"""Add settings, schedule_runs, and rules tables for Phase 3

Revision ID: 20260317_0100
Revises: 20260309_0100
Create Date: 2026-03-17 01:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260317_0100"
down_revision = "20260309_0100"
branch_labels = None
depends_on = None


def upgrade():
    # ── Settings (key-value, JSONB values) ──
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_by", sa.String(100), nullable=True),
    )

    # ── Schedule runs (pipeline execution results) ──
    op.create_table(
        "schedule_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("solver_used", sa.String(50), nullable=False, server_default="atcs_python"),
        sa.Column("dispatch_rule", sa.String(20), nullable=False, server_default="EDD"),
        sa.Column("solve_time_s", sa.Float, nullable=True),
        # Results stored as JSONB
        sa.Column("blocks", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("kpis", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("decisions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("feasibility_report", postgresql.JSONB, nullable=True),
        sa.Column("settings_snapshot", postgresql.JSONB, nullable=True),
        # Counts
        sa.Column("n_blocks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_ops", sa.Integer, nullable=False, server_default="0"),
        sa.Column("otd_pct", sa.Float, nullable=True),
        # Source ISOP hash for traceability
        sa.Column("isop_hash", sa.String(64), nullable=True, index=True),
    )
    op.create_index("ix_schedule_runs_created_at", "schedule_runs", ["created_at"])

    # ── Rules (L2 configurable rules) ──
    op.create_table(
        "rules",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rule", postgresql.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_rules_enabled", "rules", ["enabled"])


def downgrade():
    op.drop_table("rules")
    op.drop_table("schedule_runs")
    op.drop_table("settings")
