from __future__ import annotations

"""Add operator pools

Revision ID: 20260205_0400
Revises: add_calendars
Create Date: 2026-02-05 04:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260205_0400"
down_revision = "add_calendars"
branch_labels = None
depends_on = None


def upgrade():
    # Create operator_pools table
    op.create_table(
        "operator_pools",
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.String(1), nullable=False, server_default="Y"),
        sa.PrimaryKeyConstraint("pool_id"),
        sa.UniqueConstraint("code"),
    )

    # Create operator_pool_capacities table
    op.create_table(
        "operator_pool_capacities",
        sa.Column("capacity_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shift_code", sa.String(10), nullable=False),
        sa.Column("capacity_int", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pool_id"], ["operator_pools.pool_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("capacity_id"),
        sa.UniqueConstraint("pool_id", "date", "shift_code", name="uq_pool_date_shift"),
        sa.CheckConstraint("capacity_int >= 0", name="check_capacity_non_negative"),
    )

    # Create indexes
    op.create_index("ix_operator_pool_capacities_pool_id", "operator_pool_capacities", ["pool_id"])
    op.create_index("ix_operator_pool_capacities_date", "operator_pool_capacities", ["date"])


def downgrade():
    op.drop_index("ix_operator_pool_capacities_date", table_name="operator_pool_capacities")
    op.drop_index("ix_operator_pool_capacities_pool_id", table_name="operator_pool_capacities")
    op.drop_table("operator_pool_capacities")
    op.drop_table("operator_pools")
