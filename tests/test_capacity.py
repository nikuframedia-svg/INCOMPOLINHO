"""Machine capacity analytics by day and ISO week."""

from backend.analytics.capacity import compute_capacity
from backend.analytics.workforce_forecast import forecast_workforce
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.types import Segment
from backend.types import EOp, EngineData, MachineInfo


def _fixture():
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", day_capacity_min=600),
        "M2": MachineConfig(id="M2", group="Grandes", active=False),
    }
    data = EngineData(
        ops=[],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-16", "2026-03-17", "2026-03-18"],
        n_days=3,
        holidays=[1],
        machine_blocked_days={"M1": {2}},
    )
    segments = [
        Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=420,
            end_min=750,
            shift="A",
            qty=100,
            prod_min=300,
            setup_min=30,
        ),
        Segment(
            lot_id="L2",
            run_id="R2",
            machine_id="M1",
            tool_id="T2",
            day_idx=1,
            start_min=420,
            end_min=480,
            shift="A",
            qty=50,
            prod_min=30,
            setup_min=30,
        ),
    ]
    return segments, data, config


def _calendar_fixture(workdays: list[str], *, holidays: list[int] | None = None):
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", day_capacity_min=600),
    }
    data = EngineData(
        ops=[],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=workdays,
        n_days=len(workdays),
        holidays=holidays or [],
    )
    return data, config


def _daily_rows(data: EngineData, config: FactoryConfig) -> dict[int, dict]:
    rows = compute_capacity([], data, config, "day")["items"]
    return {row["day_indices"][0]: row for row in rows}


def test_daily_capacity_respects_overrides_holidays_blocks_and_inactive():
    segments, data, config = _fixture()

    rows = compute_capacity(segments, data, config, "day")["items"]
    by_key = {(row["machine_id"], row["day_indices"][0]): row for row in rows}

    assert by_key[("M1", 0)]["cap_min"] == 600
    assert by_key[("M1", 0)]["load_min"] == 330
    assert by_key[("M1", 0)]["util_pct"] == 55.0
    assert by_key[("M1", 0)]["workday_count"] == 1
    assert by_key[("M1", 1)]["cap_min"] == 0
    assert by_key[("M1", 1)]["workday_count"] == 0
    assert by_key[("M1", 1)]["overload"] is True
    assert by_key[("M1", 2)]["cap_min"] == 0
    assert by_key[("M1", 2)]["workday_count"] == 1
    assert all(("M2", day) not in by_key for day in range(3))


def test_weekend_days_have_no_capacity_even_when_not_listed_as_holidays():
    data, config = _calendar_fixture(["2026-03-21", "2026-03-22"])

    by_day = _daily_rows(data, config)

    for day_idx in (0, 1):
        assert by_day[day_idx]["cap_min"] == 0
        assert by_day[day_idx]["workday_count"] == 0


def test_extra_workday_reopens_saturday_capacity():
    data, config = _calendar_fixture(["2026-03-21", "2026-03-22"])
    config.extra_workdays = ["2026-03-21"]

    by_day = _daily_rows(data, config)

    assert by_day[0]["cap_min"] == 600
    assert by_day[0]["workday_count"] == 1
    assert by_day[1]["cap_min"] == 0
    assert by_day[1]["workday_count"] == 0


def test_explicit_holiday_wins_over_extra_workday_on_weekend():
    data, config = _calendar_fixture(["2026-03-21"])
    config.holidays = ["2026-03-21"]
    config.extra_workdays = ["2026-03-21"]

    row = _daily_rows(data, config)[0]

    assert row["cap_min"] == 0
    assert row["workday_count"] == 0


def test_week_with_five_weekdays_and_two_weekend_days_counts_five_workdays():
    data, config = _calendar_fixture(
        [
            "2026-03-16",
            "2026-03-17",
            "2026-03-18",
            "2026-03-19",
            "2026-03-20",
            "2026-03-21",
            "2026-03-22",
        ]
    )

    weekly = compute_capacity([], data, config, "week")["items"]
    row = next(item for item in weekly if item["machine_id"] == "M1")

    assert row["workday_count"] == 5
    assert row["cap_min"] == 5 * 600


def test_weekly_capacity_is_exact_sum_of_days():
    segments, data, config = _fixture()

    daily = compute_capacity(segments, data, config, "day")["items"]
    weekly = compute_capacity(segments, data, config, "week")["items"]
    m1_days = [row for row in daily if row["machine_id"] == "M1"]
    m1_week = next(row for row in weekly if row["machine_id"] == "M1")

    assert m1_week["cap_min"] == sum(row["cap_min"] for row in m1_days)
    assert m1_week["load_min"] == sum(row["load_min"] for row in m1_days)
    assert m1_week["n_setups"] == sum(row["n_setups"] for row in m1_days)
    assert m1_week["workday_count"] == 2


def test_operator_dashboards_use_exact_concurrent_headcount_and_absence():
    config = FactoryConfig(
        machines={
            "M1": MachineConfig("M1", "Grandes"),
            "M2": MachineConfig("M2", "Grandes"),
        }
    )
    config.operators[("Grandes", "A")] = 3
    data = EngineData(
        ops=[
            EOp(
                id=f"OP{index}",
                sku=f"SKU{index}",
                client="CLIENTE",
                designation="Peça",
                m=f"M{index}",
                t=f"T{index}",
                pH=100,
                sH=0,
                operators=operators,
                eco_lot=0,
                alt=None,
                stk=0,
                backlog=0,
                d=[100],
                oee=1,
                wip=0,
            )
            for index, operators in ((1, 2), (2, 1))
        ],
        machines=[
            MachineInfo(id=f"M{index}", group="Grandes", day_capacity=1020)
            for index in (1, 2)
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-16"],
        n_days=1,
        holidays=[],
        operator_blocked_intervals=[
            {
                "id": "absence",
                "group": "Grandes",
                "shift": "A",
                "start_day": 0,
                "start_min": 450,
                "end_day": 0,
                "end_min": 480,
                "count": 2,
            }
        ],
    )
    segments = [
        Segment(
            lot_id=f"L{index}",
            run_id=f"R{index}",
            machine_id=f"M{index}",
            tool_id=f"T{index}",
            day_idx=0,
            start_min=start,
            end_min=500,
            shift="A",
            qty=100,
            prod_min=500 - start,
            sku=f"SKU{index}",
        )
        for index, start in ((1, 420), (2, 440))
    ]

    workforce = forecast_workforce(segments, data, config, window=1)
    forecast = next(row for row in workforce.daily if row.shift == "A")
    operator_row = next(
        row
        for row in compute_capacity(segments, data, config)["operators"]
        if row["shift"] == "A"
    )

    assert (forecast.required, forecast.available, forecast.surplus_or_deficit) == (3, 1, -2)
    assert workforce.deficit_days == 1
    assert operator_row["load_operator_min"] == 220
    assert operator_row["peak_required"] == 3
    assert operator_row["min_available"] == 1
    assert operator_row["peak_deficit"] == 2
    assert operator_row["overload"] is True
