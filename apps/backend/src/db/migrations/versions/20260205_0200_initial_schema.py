from __future__ import annotations

"""initial_schema

Revision ID: initial_schema
Revises:
Create Date: 2026-02-05 02:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    op.execute("CREATE TYPE sourcetype AS ENUM ('XLSX', 'PDF', 'API', 'MANUAL')")
    op.execute(
        "CREATE TYPE seriessemantics AS ENUM ('NET_POSITION_AFTER_ALL_NEEDS_BY_DATE', 'PROJECTED_AVAILABLE_AFTER_ALL_NEEDS_BY_DATE', 'DEMAND_QTY_BY_DATE', 'PLANNED_PRODUCTION_QTY_BY_DATE', 'PROJECTED_STOCK_LEVEL', 'NET_REQUIREMENT', 'UNKNOWN')"
    )
    op.execute("CREATE TYPE planstatus AS ENUM ('CANDIDATE', 'OFFICIAL')")
    op.execute(
        "CREATE TYPE prstatus AS ENUM ('OPEN', 'APPROVED', 'MERGED', 'REJECTED', 'ROLLED_BACK')"
    )
    op.execute(
        "CREATE TYPE suggestiontype AS ENUM ('MOVE_ORDER', 'CHANGE_PRIORITY', 'SPLIT_OPERATION', 'OTHER')"
    )
    op.execute("CREATE TYPE suggestionstatus AS ENUM ('OPEN', 'ACCEPTED', 'REJECTED')")

    # Snapshots
    op.create_table(
        "snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "series_semantics",
            postgresql.ENUM(
                "NET_POSITION_AFTER_ALL_NEEDS_BY_DATE",
                "PROJECTED_AVAILABLE_AFTER_ALL_NEEDS_BY_DATE",
                "DEMAND_QTY_BY_DATE",
                "PLANNED_PRODUCTION_QTY_BY_DATE",
                "PROJECTED_STOCK_LEVEL",
                "NET_REQUIREMENT",
                "UNKNOWN",
                name="seriessemantics",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("setup_time_uom", sa.String(20), nullable=True),
        sa.Column("mo_uom", sa.String(20), nullable=True),
        sa.Column("trust_index_overall", sa.Numeric(3, 2), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB, nullable=False),
        sa.Index("ix_snapshots_tenant_id", "tenant_id"),
        sa.Index("ix_snapshots_snapshot_hash", "snapshot_hash"),
    )

    op.create_table(
        "snapshot_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM("XLSX", "PDF", "API", "MANUAL", name="sourcetype", create_type=False),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("file_hash_sha256", sa.String(64), nullable=False),
        sa.Column("generated_at_local", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_timezone", sa.String(50), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB, nullable=True),
        sa.Index("ix_snapshot_sources_file_hash_sha256", "file_hash_sha256"),
    )

    op.create_table(
        "items",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_sku", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("parent_sku", sa.String(100), nullable=True),
        sa.Column("lot_economic_qty", sa.Integer, nullable=True),
        sa.Index("ix_items_item_sku", "item_sku"),
    )

    op.create_table(
        "resources",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Index("ix_resources_resource_code", "resource_code"),
    )

    op.create_table(
        "tools",
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Index("ix_tools_tool_code", "tool_code"),
    )

    op.create_table(
        "routings",
        sa.Column("routing_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_sku", sa.String(100), nullable=False),
        sa.Column("routing_ref", sa.String(100), nullable=True),
        sa.Index("ix_routings_item_sku", "item_sku"),
    )

    op.create_table(
        "routing_operations",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "routing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routings.routing_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("resource_code", sa.String(100), nullable=False),
        sa.Column("tool_code", sa.String(100), nullable=True),
        sa.Column("setup_time", sa.Numeric(10, 2), nullable=True),
        sa.Column("rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("operators_required", sa.Integer, nullable=True),
        sa.Column("alt_resources", postgresql.JSONB, nullable=True),
    )

    # Plans
    op.create_table(
        "plans",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "status",
            postgresql.ENUM("CANDIDATE", "OFFICIAL", name="planstatus", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plan_params", postgresql.JSONB, nullable=False),
        sa.Column("plan_json", postgresql.JSONB, nullable=False),
        sa.Column("kpi_pack", postgresql.JSONB, nullable=False),
        sa.Column("explain_trace", postgresql.JSONB, nullable=True),
        sa.Index("ix_plans_snapshot_id", "snapshot_id"),
        sa.Index("ix_plans_snapshot_hash", "snapshot_hash"),
        sa.Index("ix_plans_plan_hash", "plan_hash"),
        sa.Index("ix_plans_status", "status"),
    )

    op.create_table(
        "workorders",
        sa.Column("workorder_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_code", sa.String(100), nullable=True),
        sa.Column("item_sku", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("day_bucket", sa.String(10), nullable=True),
        sa.Column("routing_ref", sa.String(100), nullable=True),
        sa.Index("ix_workorders_item_sku", "item_sku"),
    )

    op.create_table(
        "plan_operations",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workorder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workorders.workorder_id"),
            nullable=False,
        ),
        sa.Column("item_sku", sa.String(100), nullable=False),
        sa.Column("resource_code", sa.String(100), nullable=False),
        sa.Column("tool_code", sa.String(100), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("is_setup", sa.Boolean, nullable=False),
        sa.Column("operators_required", sa.Integer, nullable=True),
        sa.Index("ix_plan_operations_workorder_id", "workorder_id"),
        sa.Index("ix_plan_operations_resource_code", "resource_code"),
        sa.Index("ix_plan_operations_start_time", "start_time"),
        sa.Index("ix_plan_operations_end_time", "end_time"),
    )

    # Scenarios
    op.create_table(
        "scenarios",
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "scenario_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.scenario_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "baseline_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.plan_id"),
            nullable=False,
        ),
        sa.Column("baseline_plan_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Index("ix_scenario_runs_baseline_plan_id", "baseline_plan_id"),
        sa.Index("ix_scenario_runs_baseline_plan_hash", "baseline_plan_hash"),
    )

    op.create_table(
        "scenario_diffs",
        sa.Column("diff_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenario_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("diff_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # PRs
    op.create_table(
        "prs",
        sa.Column("pr_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "OPEN",
                "APPROVED",
                "MERGED",
                "REJECTED",
                "ROLLED_BACK",
                name="prstatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column(
            "scenario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.scenario_id"),
            nullable=True,
        ),
        sa.Column(
            "baseline_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.plan_id"),
            nullable=False,
        ),
        sa.Column(
            "candidate_plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.plan_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_prs_status", "status"),
        sa.Index("ix_prs_baseline_plan_id", "baseline_plan_id"),
        sa.Index("ix_prs_candidate_plan_id", "candidate_plan_id"),
    )

    op.create_table(
        "pr_approvals",
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prs.pr_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approver_id", sa.String(255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
    )

    # Suggestions
    op.create_table(
        "suggestions",
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "type",
            postgresql.ENUM(
                "MOVE_ORDER",
                "CHANGE_PRIORITY",
                "SPLIT_OPERATION",
                "OTHER",
                name="suggestiontype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "OPEN", "ACCEPTED", "REJECTED", name="suggestionstatus", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "created_from",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenarios.scenario_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recommended_action_structured", postgresql.JSONB, nullable=False),
        sa.Index("ix_suggestions_type", "type"),
        sa.Index("ix_suggestions_status", "status"),
    )

    op.create_table(
        "impact_cases",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "suggestion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suggestions.suggestion_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("baseline_kpis", postgresql.JSONB, nullable=False),
        sa.Column("scenario_kpis", postgresql.JSONB, nullable=False),
        sa.Column("expected_value_eur", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
    )

    op.create_table(
        "impact_results",
        sa.Column("result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "suggestion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suggestions.suggestion_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("measured_kpis", postgresql.JSONB, nullable=False),
        sa.Column("measured_value_eur", sa.Numeric(12, 2), nullable=True),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=True),
    )

    # Audit Log
    op.create_table(
        "audit_log",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("before", postgresql.JSONB, nullable=True),
        sa.Column("after", postgresql.JSONB, nullable=True),
        sa.Column("audit_metadata", postgresql.JSONB, nullable=True),
        sa.Index("ix_audit_log_timestamp", "timestamp"),
        sa.Index("ix_audit_log_actor", "actor"),
        sa.Index("ix_audit_log_action", "action"),
        sa.Index("ix_audit_log_correlation_id", "correlation_id"),
        sa.Index("ix_audit_log_entity_type", "entity_type"),
        sa.Index("ix_audit_log_entity_id", "entity_id"),
    )

    # Integration Outbox
    op.create_table(
        "integration_outbox",
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("processed", sa.Boolean, nullable=False, default=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Index("ix_integration_outbox_created_at", "created_at"),
        sa.Index("ix_integration_outbox_idempotency_key", "idempotency_key"),
        sa.Index("ix_integration_outbox_aggregate_id", "aggregate_id"),
        sa.Index("ix_integration_outbox_event_type", "event_type"),
        sa.Index("ix_integration_outbox_processed", "processed"),
        sa.UniqueConstraint(
            "idempotency_key", "aggregate_id", name="uq_outbox_idempotency_aggregate"
        ),
    )


def downgrade() -> None:
    op.drop_table("integration_outbox")
    op.drop_table("audit_log")
    op.drop_table("impact_results")
    op.drop_table("impact_cases")
    op.drop_table("suggestions")
    op.drop_table("pr_approvals")
    op.drop_table("prs")
    op.drop_table("scenario_diffs")
    op.drop_table("scenario_runs")
    op.drop_table("scenarios")
    op.drop_table("plan_operations")
    op.drop_table("workorders")
    op.drop_table("plans")
    op.drop_table("routing_operations")
    op.drop_table("routings")
    op.drop_table("tools")
    op.drop_table("resources")
    op.drop_table("items")
    op.drop_table("snapshot_sources")
    op.drop_table("snapshots")

    op.execute("DROP TYPE IF EXISTS suggestionstatus")
    op.execute("DROP TYPE IF EXISTS suggestiontype")
    op.execute("DROP TYPE IF EXISTS prstatus")
    op.execute("DROP TYPE IF EXISTS planstatus")
    op.execute("DROP TYPE IF EXISTS seriessemantics")
    op.execute("DROP TYPE IF EXISTS sourcetype")
