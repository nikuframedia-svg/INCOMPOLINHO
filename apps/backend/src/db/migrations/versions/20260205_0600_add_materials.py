from __future__ import annotations

"""Add materials and calcos

Revision ID: 20260205_0600
Revises: 20260205_0500
Create Date: 2026-02-05 06:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260205_0600"
down_revision = "20260205_0500"
branch_labels = None
depends_on = None


def upgrade():
    # Create materials table
    op.create_table(
        "materials",
        sa.Column("material_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("material_code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("uom", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.String(1), nullable=False, server_default="Y"),
        sa.PrimaryKeyConstraint("material_id"),
        sa.UniqueConstraint("material_code"),
    )

    # Create material_lots table
    op.create_table(
        "material_lots",
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_code", sa.String(100), nullable=False, unique=True),
        sa.Column("qty", sa.Numeric(10, 2), nullable=False),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["materials.material_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("lot_id"),
        sa.UniqueConstraint("lot_code"),
    )

    # Create material_arrivals table
    op.create_table(
        "material_arrivals",
        sa.Column("arrival_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qty", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["materials.material_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("arrival_id"),
    )

    # Create tool_material_requirements table
    op.create_table(
        "tool_material_requirements",
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tool_code", sa.String(100), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumption_rate", sa.Numeric(10, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["materials.material_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("requirement_id"),
        sa.UniqueConstraint("tool_code", "material_id", name="uq_tool_material"),
    )

    # Create calcos table
    op.create_table(
        "calcos",
        sa.Column("calco_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("calco_code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.String(1), nullable=False, server_default="Y"),
        sa.PrimaryKeyConstraint("calco_id"),
        sa.UniqueConstraint("calco_code"),
    )

    # Create tool_calco_maps table
    op.create_table(
        "tool_calco_maps",
        sa.Column("map_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tool_code", sa.String(100), nullable=False),
        sa.Column("calco_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["calco_id"], ["calcos.calco_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("map_id"),
        sa.UniqueConstraint("tool_code", "calco_id", name="uq_tool_calco"),
    )

    # Create indexes
    op.create_index("ix_materials_material_code", "materials", ["material_code"])
    op.create_index("ix_material_lots_material_id", "material_lots", ["material_id"])
    op.create_index("ix_material_arrivals_material_id", "material_arrivals", ["material_id"])
    op.create_index(
        "ix_tool_material_requirements_tool_code", "tool_material_requirements", ["tool_code"]
    )
    op.create_index(
        "ix_tool_material_requirements_material_id", "tool_material_requirements", ["material_id"]
    )
    op.create_index("ix_calcos_calco_code", "calcos", ["calco_code"])
    op.create_index("ix_tool_calco_maps_tool_code", "tool_calco_maps", ["tool_code"])
    op.create_index("ix_tool_calco_maps_calco_id", "tool_calco_maps", ["calco_id"])


def downgrade():
    op.drop_index("ix_tool_calco_maps_calco_id", table_name="tool_calco_maps")
    op.drop_index("ix_tool_calco_maps_tool_code", table_name="tool_calco_maps")
    op.drop_index("ix_calcos_calco_code", table_name="calcos")
    op.drop_index(
        "ix_tool_material_requirements_material_id", table_name="tool_material_requirements"
    )
    op.drop_index(
        "ix_tool_material_requirements_tool_code", table_name="tool_material_requirements"
    )
    op.drop_index("ix_material_arrivals_material_id", table_name="material_arrivals")
    op.drop_index("ix_material_lots_material_id", table_name="material_lots")
    op.drop_index("ix_materials_material_code", table_name="materials")
    op.drop_table("tool_calco_maps")
    op.drop_table("calcos")
    op.drop_table("tool_material_requirements")
    op.drop_table("material_arrivals")
    op.drop_table("material_lots")
    op.drop_table("materials")
