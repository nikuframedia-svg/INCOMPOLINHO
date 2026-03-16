from __future__ import annotations

"""Add Decision Ledger and Learning Proposals tables

Revision ID: 20260308_0100
Revises: 20260305_0000
Create Date: 2026-03-08 01:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260308_0100"
down_revision = "20260305_0000"
branch_labels = None
depends_on = None


def upgrade():
    # Decision Ledger — registo imutável de desvios
    op.create_table(
        "decision_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("decision_type", sa.String(50), nullable=False, index=True),
        sa.Column("optimal_state", postgresql.JSONB, nullable=False),
        sa.Column("proposed_state", postgresql.JSONB, nullable=False),
        sa.Column("deviation_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("incentive_category", sa.String(30), nullable=False),
        sa.Column("declared_reason", sa.Text, nullable=False),
        sa.Column("governance_level", sa.String(2), nullable=False),
        sa.Column("contrafactual", postgresql.JSONB, nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", postgresql.JSONB, nullable=True),
        sa.Column("outcome_variance", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )

    # Index composto para queries frequentes
    op.create_index(
        "ix_decision_entries_tenant_category",
        "decision_entries",
        ["tenant_id", "incentive_category"],
    )

    # Learning Proposals — propostas de ajuste quando variance > 10%
    op.create_table(
        "learning_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("decision_entries.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("variance_type", sa.String(30), nullable=False),
        sa.Column("variance_value", sa.Numeric(8, 4), nullable=False),
        sa.Column("proposed_adjustment", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="pending", index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("learning_proposals")
    op.drop_index("ix_decision_entries_tenant_category", table_name="decision_entries")
    op.drop_table("decision_entries")
