from __future__ import annotations

"""Add stock_alerts table for alert persistence

Revision ID: 20260309_0100
Revises: 20260308_0100
Create Date: 2026-03-09 01:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260309_0100"
down_revision = "20260308_0100"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", sa.String(100), nullable=False, index=True),
        sa.Column("tool_code", sa.String(50), nullable=False, index=True),
        sa.Column("machine", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("action_by", sa.String(100), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade():
    op.drop_table("stock_alerts")
