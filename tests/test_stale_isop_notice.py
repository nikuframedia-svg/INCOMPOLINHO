"""The plan warns in plain Portuguese when its ISOP starts before today.

Usage of 12/10/2026: the active plan still used the ISOP of 09/10 and counted
Friday 09/10 as already produced, with nothing on screen saying so. The
notice reads only the plan's calendar and the factory's "today" (the same
rule as ``/api/data/today``); it never changes the plan.
"""

from __future__ import annotations

import copy
import functools
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import stale_isop
from backend.plans.stale_isop import stale_isop_notice
from backend.types import EngineData

LISBON = ZoneInfo("Europe/Lisbon")
CONFIG = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
NOTICE_0910 = (
    "O plano usa o ISOP de 09/10. Os dias anteriores a hoje são considerados já "
    "produzidos. Carregue o ISOP de hoje para atualizar o plano."
)


def _isop(first: str, n_days: int = 20) -> EngineData:
    """Calendar days from ``first``, weekends marked as ISOP holidays."""

    start = date.fromisoformat(first)
    days = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]
    return EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={},
        workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _at(day: str, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=LISBON)


def test_isop_of_friday_on_monday_tells_the_planner():
    """The real case: ISOP of Friday 09/10, opened on Monday 12/10."""

    assert stale_isop_notice(_isop("2026-10-09"), CONFIG, now=_at("2026-10-12")) == NOTICE_0910


@pytest.mark.parametrize("today", ["2026-10-08", "2026-10-09"])
def test_isop_of_today_or_a_future_isop_has_no_notice(today):
    assert stale_isop_notice(_isop("2026-10-09"), CONFIG, now=_at(today)) is None


def test_only_working_days_before_today_count():
    """An ISOP that starts on Saturday is still the current one on Monday."""

    data = _isop("2026-10-10")
    assert stale_isop_notice(data, CONFIG, now=_at("2026-10-12")) is None
    notice = stale_isop_notice(data, CONFIG, now=_at("2026-10-13"))
    assert notice is not None and notice.startswith("O plano usa o ISOP de 10/10.")


def test_factory_holiday_and_extra_workday_follow_the_calendar():
    """5 October is a holiday; an extra Saturday is a working day."""

    holiday = FactoryConfig(machines=CONFIG.machines, holidays=["2026-10-05"])
    assert stale_isop_notice(_isop("2026-10-05"), holiday, now=_at("2026-10-06")) is None
    assert stale_isop_notice(_isop("2026-10-05"), CONFIG, now=_at("2026-10-06")) is not None

    saturday = FactoryConfig(machines=CONFIG.machines, extra_workdays=["2026-10-10"])
    assert stale_isop_notice(_isop("2026-10-10"), CONFIG, now=_at("2026-10-12")) is None
    assert stale_isop_notice(_isop("2026-10-10"), saturday, now=_at("2026-10-12")) is not None


def test_today_is_the_factory_day_in_lisbon():
    """23:30 UTC on Friday is already Saturday in Lisbon (summer time)."""

    data = _isop("2026-10-09")
    friday_night = datetime(2026, 10, 9, 22, 30, tzinfo=timezone.utc)  # 23:30 in Lisbon
    after_midnight = datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)  # 00:30 on 10/10
    assert stale_isop_notice(data, CONFIG, now=friday_night) is None
    assert stale_isop_notice(data, CONFIG, now=after_midnight) == NOTICE_0910


def test_an_isop_that_ended_before_today_does_not_claim_production():
    """When today is past the ISOP, the plan has no day for today; the notice
    asks for the new ISOP without saying how past days were counted."""

    notice = stale_isop_notice(_isop("2026-02-27", n_days=10), CONFIG, now=_at("2026-10-12"))
    assert notice == (
        "O plano usa o ISOP de 27/02, que já não chega até hoje. "
        "Carregue o ISOP de hoje para atualizar o plano."
    )


def test_no_calendar_no_notice():
    empty = EngineData(ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=0)
    assert stale_isop_notice(empty, CONFIG, now=_at("2026-10-12")) is None
    assert stale_isop_notice(_isop("2026-10-09"), None, now=_at("2026-10-12")) is None


@pytest.fixture
def current_plan_state(tmp_path):
    """A current (non-legacy) plan of an ISOP starting on Wednesday 07/10."""

    from backend.copilot.state import state
    from backend.plans.store import PlansStore
    from backend.scheduler.scheduler import schedule_all
    from tests.test_legacy_material_plan import CONFIG as PLAN_CONFIG
    from tests.test_legacy_material_plan import _scenario

    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    store = PlansStore(tmp_path / "stale-isop.db")
    data = _scenario()
    config = copy.deepcopy(PLAN_CONFIG)
    state.engine_data = data
    state.config = config
    state.default_config = config
    state.dataset_info = None
    state.active_mutations = []
    state.manual_edits = []
    state.saved_schedule = None
    state.saved_mutations = None
    state.saved_manual_edits = None
    state.plans_store = store
    state.update_schedule(schedule_all(data, config=copy.deepcopy(config)))
    yield state
    store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def _pin_today(monkeypatch, day: str) -> None:
    monkeypatch.setattr(
        stale_isop, "stale_isop_notice",
        functools.partial(stale_isop_notice, now=_at(day)),
    )


def test_plan_view_carries_the_notice_and_leaves_the_plan_untouched(
    current_plan_state, monkeypatch,
):
    from backend.plans import serialize

    state = current_plan_state
    before = serialize.serialize_snapshot(state), state.plan_revision
    client = TestClient(app)
    try:
        _pin_today(monkeypatch, "2026-10-07")
        fresh = client.get("/api/data/plan-view")
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["plan_notices"] == []

        _pin_today(monkeypatch, "2026-10-12")
        old = client.get("/api/data/plan-view")
        assert old.status_code == 200, old.text
        assert old.json()["plan_notices"] == [
            "O plano usa o ISOP de 07/10. Os dias anteriores a hoje são considerados já "
            "produzidos. Carregue o ISOP de hoje para atualizar o plano."
        ]
        assert old.json()["plan_revision"] == fresh.json()["plan_revision"]
    finally:
        client.close()
    assert (serialize.serialize_snapshot(state), state.plan_revision) == before
