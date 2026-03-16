from __future__ import annotations

"""Drop orphan tables from deleted domains

Removes tables created by migrations for domains that were deleted
during the 2026-03-04 backend cleanup: plan_jobs, calendars,
operator_pools, materials, and calcos.

Revision ID: 20260305_0000
Revises: 20260205_0600
Create Date: 2026-03-05 00:00:00

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0000"
down_revision = "20260205_0600"
branch_labels = None
depends_on = None


def upgrade():
    # Drop materials domain tables (must drop children before parents)
    op.execute("DROP TABLE IF EXISTS tool_calco_maps CASCADE")
    op.execute("DROP TABLE IF EXISTS calcos CASCADE")
    op.execute("DROP TABLE IF EXISTS tool_material_requirements CASCADE")
    op.execute("DROP TABLE IF EXISTS material_arrivals CASCADE")
    op.execute("DROP TABLE IF EXISTS material_lots CASCADE")
    op.execute("DROP TABLE IF EXISTS materials CASCADE")

    # Drop operator_pools domain tables
    op.execute("DROP TABLE IF EXISTS operator_pool_capacities CASCADE")
    op.execute("DROP TABLE IF EXISTS operator_pools CASCADE")

    # Drop calendars domain tables
    op.execute("DROP TABLE IF EXISTS resource_calendars CASCADE")
    op.execute("DROP TABLE IF EXISTS calendar_days CASCADE")
    op.execute("DROP TABLE IF EXISTS shift_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS calendars CASCADE")

    # Drop plan_jobs table
    op.execute("DROP TABLE IF EXISTS plan_jobs CASCADE")

    # Drop orphan enum types
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS shiftcode")


def downgrade():
    # Irreversible — these domains were deleted from the codebase.
    # The original migration files still exist for reference.
    pass
