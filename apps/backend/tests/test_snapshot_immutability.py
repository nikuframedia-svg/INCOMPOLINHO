# Testes para imutabilidade de snapshots
# Conforme SP-BE-04

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.core.errors import APIException
from src.domain.models.snapshot import Snapshot
from src.domain.snapshot.repository import SnapshotRepository
from src.main import app


def _pg_available() -> bool:
    """Check if PostgreSQL is accessible."""
    try:
        from src.db.base import SessionLocal

        db = SessionLocal()
        db.execute("SELECT 1")  # type: ignore[arg-type]
        db.close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL not available")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    """Fixture para sessão de DB (mock)"""
    # Em testes reais, usar DB de teste
    from src.db.base import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@requires_pg
def test_seal_snapshot(db_session: Session):
    """Testa que selar snapshot funciona"""
    # Criar snapshot de teste
    snapshot = Snapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        created_at=datetime.utcnow(),
        snapshot_hash="test_hash",
        series_semantics="DEMAND_QTY_BY_DATE",
        trust_index_overall=0.9,
        snapshot_json={},
    )
    db_session.add(snapshot)
    db_session.commit()

    # Selar snapshot
    sealed = SnapshotRepository.seal(db_session, snapshot.snapshot_id)

    assert sealed.sealed_at is not None
    assert sealed.snapshot_id == snapshot.snapshot_id


@requires_pg
def test_seal_already_sealed_fails(db_session: Session):
    """Testa que selar snapshot já selado falha"""
    # Criar snapshot selado
    snapshot = Snapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        created_at=datetime.utcnow(),
        snapshot_hash="test_hash",
        series_semantics="DEMAND_QTY_BY_DATE",
        trust_index_overall=0.9,
        sealed_at=datetime.utcnow(),
        snapshot_json={},
    )
    db_session.add(snapshot)
    db_session.commit()

    # Tentar selar novamente deve falhar
    with pytest.raises(APIException) as exc_info:
        SnapshotRepository.seal(db_session, snapshot.snapshot_id)

    assert exc_info.value.status_code == 400
    assert "already sealed" in exc_info.value.detail.lower()


@requires_pg
def test_update_check_immutability_sealed(db_session: Session):
    """Testa que tentar atualizar snapshot selado falha"""
    # Criar snapshot selado
    snapshot = Snapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        created_at=datetime.utcnow(),
        snapshot_hash="test_hash",
        series_semantics="DEMAND_QTY_BY_DATE",
        trust_index_overall=0.9,
        sealed_at=datetime.utcnow(),
        snapshot_json={},
    )
    db_session.add(snapshot)
    db_session.commit()

    # Tentar atualizar deve falhar
    with pytest.raises(APIException) as exc_info:
        SnapshotRepository.update_check_immutability(db_session, snapshot.snapshot_id)

    assert exc_info.value.status_code == 400
    assert "sealed" in exc_info.value.detail.lower() or "immutable" in exc_info.value.detail.lower()


@requires_pg
def test_update_check_immutability_not_sealed(db_session: Session):
    """Testa que snapshot não selado pode ser atualizado (check passa)"""
    # Criar snapshot não selado
    snapshot = Snapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        created_at=datetime.utcnow(),
        snapshot_hash="test_hash",
        series_semantics="DEMAND_QTY_BY_DATE",
        trust_index_overall=0.9,
        snapshot_json={},
    )
    db_session.add(snapshot)
    db_session.commit()

    # Check deve passar
    result = SnapshotRepository.update_check_immutability(db_session, snapshot.snapshot_id)
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.sealed_at is None
