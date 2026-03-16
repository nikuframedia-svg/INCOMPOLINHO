from __future__ import annotations

"""Add run events

Revision ID: 20260205_0500
Revises: 20260205_0400
Create Date: 2026-02-05 05:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260205_0500"
down_revision = "20260205_0400"
branch_labels = None
depends_on = None


def upgrade():
    # Create enum RunEventType
    run_event_type_enum = postgresql.ENUM(
        "MachineDown",
        "MachineUp",
        "OperatorAbsent",
        "OperatorBack",
        "QualityHold",
        "ScrapEvent",
        name="runeventtype",
        create_type=False,
    )
    run_event_type_enum.create(op.get_bind(), checkfirst=True)

    # Create run_events table
    op.create_table(
        "run_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_type",
            postgresql.ENUM(
                "MachineDown",
                "MachineUp",
                "OperatorAbsent",
                "OperatorBack",
                "QualityHold",
                "ScrapEvent",
                name="runeventtype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_code", sa.String(100), nullable=True),
        sa.Column("pool_code", sa.String(10), nullable=True),
        sa.Column("workorder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date", sa.String(10), nullable=True),
        sa.Column("shift_code", sa.String(10), nullable=True),
        sa.Column("operators_count", sa.Integer(), nullable=True),
        sa.Column("scrap_qty", sa.Numeric(10, 2), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.scenario_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )

    # Create indexes
    op.create_index("ix_run_events_event_type", "run_events", ["event_type"])
    op.create_index("ix_run_events_occurred_at", "run_events", ["occurred_at"])
    op.create_index("ix_run_events_resource_code", "run_events", ["resource_code"])


def downgrade():
    op.drop_index("ix_run_events_resource_code", table_name="run_events")
    op.drop_index("ix_run_events_occurred_at", table_name="run_events")
    op.drop_index("ix_run_events_event_type", table_name="run_events")
    op.drop_table("run_events")
    op.execute("DROP TYPE IF EXISTS runeventtype")
