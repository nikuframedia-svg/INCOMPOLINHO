# Snapshot service
# Conforme SP-BE-03

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ...core.logging import get_logger
from ...domain.models.snapshot import (
    Item,
    Resource,
    Routing,
    RoutingOperation,
    Snapshot,
    SnapshotSource,
    Tool,
)
from .hash import calculate_snapshot_hash

logger = get_logger(__name__)


def persist_snapshot(
    db: Session, snapshot: dict[str, Any], file_hash: str, snapshot_hash: str | None = None
) -> Snapshot:
    """Persiste snapshot na base de dados"""
    if snapshot_hash is None:
        snapshot_hash = calculate_snapshot_hash(snapshot)

    # Verificar se já existe snapshot com mesmo hash
    existing = db.query(Snapshot).filter(Snapshot.snapshot_hash == snapshot_hash).first()
    if existing:
        logger.info(f"Snapshot with hash {snapshot_hash} already exists: {existing.snapshot_id}")
        return existing

    # Use trust_index from snapshot data (DQA module removed)
    trust_index_data = snapshot.get("trust_index", {"overall": 1.0})

    # Criar snapshot
    db_snapshot = Snapshot(
        snapshot_id=snapshot["snapshot_id"],
        tenant_id=snapshot["tenant_id"],
        created_at=datetime.fromisoformat(snapshot["created_at"].replace("Z", "+00:00")),
        snapshot_hash=snapshot_hash,
        series_semantics=snapshot["semantics"]["series_semantics"],
        setup_time_uom=snapshot["semantics"].get("setup_time_uom"),
        mo_uom=snapshot["semantics"].get("mo_uom"),
        trust_index_overall=trust_index_data["overall"],
        snapshot_json=snapshot,
    )

    db.add(db_snapshot)

    # Criar source
    source_data = snapshot["sources"][0] if snapshot.get("sources") else {}
    db_source = SnapshotSource(
        source_id=source_data.get("source_id", str(uuid4())),
        snapshot_id=db_snapshot.snapshot_id,
        type=source_data.get("type", "XLSX"),
        filename=source_data.get("filename"),
        file_hash_sha256=file_hash,
        generated_at_local=datetime.fromisoformat(source_data["generated_at_local"])
        if source_data.get("generated_at_local")
        else None,
        source_timezone=source_data.get("source_timezone"),
        source_metadata=source_data.get("source_metadata"),
    )
    db.add(db_source)

    # Criar items
    for item_data in snapshot.get("master_data", {}).get("items", []):
        db_item = Item(
            item_id=str(uuid4()),
            snapshot_id=db_snapshot.snapshot_id,
            item_sku=item_data["item_sku"],
            name=item_data.get("name"),
            parent_sku=item_data.get("parent_sku"),
            lot_economic_qty=item_data.get("lot_economic_qty"),
        )
        db.add(db_item)

    # Criar resources
    for resource_data in snapshot.get("master_data", {}).get("resources", []):
        db_resource = Resource(
            resource_id=str(uuid4()),
            snapshot_id=db_snapshot.snapshot_id,
            resource_code=resource_data["resource_code"],
            name=resource_data.get("name"),
            resource_type=resource_data.get("resource_type"),
        )
        db.add(db_resource)

    # Criar tools
    for tool_data in snapshot.get("master_data", {}).get("tools", []):
        db_tool = Tool(
            tool_id=str(uuid4()),
            snapshot_id=db_snapshot.snapshot_id,
            tool_code=tool_data["tool_code"],
            name=tool_data.get("name"),
        )
        db.add(db_tool)

    # Criar routings
    for routing_data in snapshot.get("routing", []):
        db_routing = Routing(
            routing_id=str(uuid4()),
            snapshot_id=db_snapshot.snapshot_id,
            item_sku=routing_data["item_sku"],
            routing_ref=routing_data.get("routing_ref"),
        )
        db.add(db_routing)

        # Criar routing operations
        for op_data in routing_data.get("operations", []):
            db_op = RoutingOperation(
                operation_id=str(uuid4()),
                routing_id=db_routing.routing_id,
                sequence=op_data.get("sequence", 1),
                resource_code=op_data["resource_code"],
                tool_code=op_data.get("tool_code"),
                setup_time=op_data.get("setup_time"),
                rate=op_data.get("rate"),
                operators_required=op_data.get("operators_required", 1),
                alt_resources=op_data.get("alt_resources", []),
            )
            db.add(db_op)

    db.commit()
    db.refresh(db_snapshot)

    logger.info(f"Snapshot persisted: {db_snapshot.snapshot_id} (hash: {snapshot_hash})")

    return db_snapshot
