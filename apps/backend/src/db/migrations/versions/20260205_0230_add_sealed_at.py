from __future__ import annotations

"""add_sealed_at

Revision ID: add_sealed_at
Revises: initial_schema
Create Date: 2026-02-05 02:30:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_sealed_at"
down_revision = "initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adicionar coluna sealed_at à tabela snapshots
    op.add_column("snapshots", sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_snapshots_sealed_at", "snapshots", ["sealed_at"])


def downgrade() -> None:
    op.drop_index("ix_snapshots_sealed_at", table_name="snapshots")
    op.drop_column("snapshots", "sealed_at")
