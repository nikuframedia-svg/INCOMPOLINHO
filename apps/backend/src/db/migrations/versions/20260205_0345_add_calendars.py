from __future__ import annotations

"""add_calendars

Revision ID: add_calendars
Revises: add_plan_jobs
Create Date: 2026-02-05 03:45:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_calendars"
down_revision = "add_plan_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Criar enum ShiftCode
    shift_code_enum = postgresql.ENUM("X", "Y", "OFF", "NIGHT", name="shiftcode", create_type=False)
    shift_code_enum.create(op.get_bind(), checkfirst=True)

    # Criar tabela calendars
    op.create_table(
        "calendars",
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freeze_window_policy", postgresql.JSONB, nullable=True),
    )

    op.create_index("ix_calendars_code", "calendars", ["code"], unique=True)
    op.create_index("ix_calendars_is_default", "calendars", ["is_default"])

    # Criar tabela shift_templates
    op.create_table(
        "shift_templates",
        sa.Column("shift_template_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shift_code", shift_code_enum, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_local", sa.Time(), nullable=False),
        sa.Column("end_local", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["calendar_id"], ["calendars.calendar_id"], ondelete="CASCADE"),
    )

    op.create_index("ix_shift_templates_calendar_id", "shift_templates", ["calendar_id"])

    # Criar tabela calendar_days
    op.create_table(
        "calendar_days",
        sa.Column("calendar_day_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("is_working_day", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("shifts", postgresql.JSONB, nullable=True),
        sa.ForeignKeyConstraint(["calendar_id"], ["calendars.calendar_id"], ondelete="CASCADE"),
    )

    op.create_index("ix_calendar_days_calendar_id", "calendar_days", ["calendar_id"])
    op.create_index("ix_calendar_days_date", "calendar_days", ["date"])
    op.create_unique_constraint(
        "uq_calendar_days_calendar_date", "calendar_days", ["calendar_id", "date"]
    )

    # Criar tabela resource_calendars
    op.create_table(
        "resource_calendars",
        sa.Column("resource_calendar_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_code", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("overrides", postgresql.JSONB, nullable=True),
        sa.ForeignKeyConstraint(["calendar_id"], ["calendars.calendar_id"], ondelete="CASCADE"),
    )

    op.create_index("ix_resource_calendars_calendar_id", "resource_calendars", ["calendar_id"])
    op.create_index("ix_resource_calendars_resource_code", "resource_calendars", ["resource_code"])
    op.create_unique_constraint(
        "uq_resource_calendars_resource_calendar",
        "resource_calendars",
        ["resource_code", "calendar_id"],
    )


def downgrade() -> None:
    op.drop_table("resource_calendars")
    op.drop_table("calendar_days")
    op.drop_table("shift_templates")
    op.drop_table("calendars")
    op.execute("DROP TYPE IF EXISTS shiftcode")
