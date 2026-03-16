# Testes para Run Events
# Conforme SP-BE-12

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.domain.run_events.models import RunEvent, RunEventType
from src.domain.run_events.service import RunEventService


@pytest.fixture
def db_session():
    """Fixture para sessão de DB (mock)"""
    from unittest.mock import MagicMock

    from sqlalchemy.orm import Session

    session = MagicMock(spec=Session)
    yield session
    session.close()


def test_create_event_machine_down(db_session):
    """Testa criação de evento MachineDown"""
    service = RunEventService(db_session)

    occurred_at = datetime(2026, 1, 1, 10, 0, 0)
    start_time = datetime(2026, 1, 1, 10, 0, 0)
    end_time = datetime(2026, 1, 1, 14, 0, 0)

    # Mock repository
    mock_event = RunEvent(
        event_id=None,
        event_type=RunEventType.MACHINE_DOWN,
        occurred_at=occurred_at,
        resource_code="M01",
        start_time=start_time,
        end_time=end_time,
    )
    service.repo.create_event = MagicMock(return_value=mock_event)
    service.repo.get_by_event_id_string = MagicMock(return_value=None)

    event = service.create_event(
        event_type=RunEventType.MACHINE_DOWN,
        occurred_at=occurred_at,
        resource_code="M01",
        start_time=start_time,
        end_time=end_time,
    )

    assert event.event_type == RunEventType.MACHINE_DOWN
    assert event.resource_code == "M01"


def test_create_event_idempotent(db_session):
    """Testa que criação de evento é idempotente"""
    service = RunEventService(db_session)

    event_id = "test-event-id"
    occurred_at = datetime(2026, 1, 1, 10, 0, 0)

    # Mock existing event
    existing_event = RunEvent(
        event_id=None,
        event_type=RunEventType.MACHINE_DOWN,
        occurred_at=occurred_at,
    )
    service.repo.get_by_event_id_string = MagicMock(return_value=existing_event)

    event = service.create_event(
        event_type=RunEventType.MACHINE_DOWN,
        occurred_at=occurred_at,
        event_id=event_id,
    )

    # Deve retornar evento existente
    assert event == existing_event
    # Não deve criar novo (verificar que get_by_event_id_string foi chamado)
    service.repo.get_by_event_id_string.assert_called_once_with(event_id)


def test_create_event_operator_absent(db_session):
    """Testa criação de evento OperatorAbsent"""
    service = RunEventService(db_session)

    occurred_at = datetime(2026, 1, 1, 6, 0, 0)

    mock_event = RunEvent(
        event_id=None,
        event_type=RunEventType.OPERATOR_ABSENT,
        occurred_at=occurred_at,
        pool_code="X",
        date="2026-01-01",
        shift_code="X",
        operators_count=2,
    )
    service.repo.create_event = MagicMock(return_value=mock_event)
    service.repo.get_by_event_id_string = MagicMock(return_value=None)

    event = service.create_event(
        event_type=RunEventType.OPERATOR_ABSENT,
        occurred_at=occurred_at,
        pool_code="X",
        date="2026-01-01",
        shift_code="X",
        operators_count=2,
    )

    assert event.event_type == RunEventType.OPERATOR_ABSENT
    assert event.pool_code == "X"
    assert event.operators_count == 2
