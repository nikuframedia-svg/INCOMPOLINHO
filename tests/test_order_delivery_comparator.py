"""Delivery per order in the shared comparator; the priority-rotation
neighbourhood (AGENTS §1.2, §6; Fase B3, 11/10/2026)."""

from __future__ import annotations

import math

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.improvement import (
    PlanFacts,
    SetupSummary,
    default_generators,
    improve_plan,
    improvement_better,
    improvement_key,
    plan_facts,
    regresses_reference,
)
from backend.scheduler.operational_audit import find_output_priority_anomalies
from backend.scheduler.priority import (
    delivery_improves,
    delivery_is_complete,
    delivery_not_worse,
    delivery_priority_key,
    has_order_delivery,
    order_delivery_metrics,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo


class _Service:
    def __init__(self, tardiness: float) -> None:
        self.tardiness = tardiness


def _orders(*tardiness: float, sku: str = "A") -> dict:
    return {(sku, "C", day, 10, -10, 0): _Service(t) for day, t in enumerate(tardiness)}


def _score(**values) -> dict:
    base = {
        "otd": 90.0, "otd_d": 95.0, "otd_d_failures": 2, "tardy_count": 3,
        "total_tardiness": 9, "max_tardiness": 4,
        "orders_late": 2, "orders_unready": 0, "order_late_days": 5.0,
    }
    return {**base, **values}


# ── Metrics ──────────────────────────────────────────────────────────────


def test_order_metrics_count_late_and_never_ready_orders():
    metrics = order_delivery_metrics(
        {**_orders(0.0, 2.0, math.inf), **_orders(3.0, sku="P")}, {"P": 5},
    )

    assert metrics["orders_late"] == 3
    assert metrics["orders_unready"] == 1
    # Never-ready orders are counted, not summed: the total stays finite.
    assert metrics["order_late_days"] == 5.0
    assert metrics["priority_orders_late"] == 1
    assert metrics["priority_order_late_weight"] == 5
    assert metrics["priority_order_late_days_weighted"] == 15.0


# ── Key ──────────────────────────────────────────────────────────────────


def test_lot_tardiness_does_not_rank_when_orders_are_known():
    reference = _score()
    fewer_late_lots = _score(tardy_count=1, total_tardiness=2, max_tardiness=1, otd=97.0)

    assert delivery_priority_key(fewer_late_lots) == delivery_priority_key(reference)
    assert not delivery_improves(fewer_late_lots, reference)
    assert delivery_not_worse(reference, fewer_late_lots)
    # The historical lot key would have preferred it.
    assert delivery_priority_key(fewer_late_lots, per_order=False) < delivery_priority_key(
        reference, per_order=False,
    )


def test_late_orders_then_order_days_then_otd_d_failures_decide():
    reference = _score()

    assert delivery_improves(_score(orders_late=1, total_tardiness=30), reference)
    assert delivery_improves(_score(order_late_days=4.0, tardy_count=9), reference)
    assert delivery_improves(_score(otd_d_failures=1), reference)
    assert not delivery_not_worse(_score(orders_late=3, tardy_count=0), reference)
    # More late orders outweighs fewer days late.
    assert not delivery_not_worse(_score(orders_late=3, order_late_days=1.0), reference)


def test_never_ready_order_ranks_after_the_late_count():
    reference = _score(orders_late=2, orders_unready=0, order_late_days=5.0)
    unready = _score(orders_late=2, orders_unready=1, order_late_days=2.0)

    assert not delivery_not_worse(unready, reference)


def test_completeness_is_per_order():
    on_time = _score(
        orders_late=0, order_late_days=0.0, otd_d=100.0, otd_d_failures=0,
        tardy_count=4, otd=80.0,
    )

    assert delivery_is_complete(on_time)
    assert delivery_priority_key(on_time)[0] == 0.0


def test_scores_without_order_metrics_keep_the_lot_basis_on_both_sides():
    legacy = {"tardy_count": 1, "otd": 90.0, "otd_d": 100.0}
    per_order = _score(orders_late=0, order_late_days=0.0, otd_d_failures=0)

    assert not has_order_delivery(legacy)
    # One side without order metrics: both compared on the lot basis.
    assert delivery_not_worse(legacy, {**per_order, "tardy_count": 1, "otd": 90.0})
    assert not delivery_not_worse(legacy, {"tardy_count": 0, "otd": 100.0, "otd_d": 100.0})


# ── Improvement contract (the rev90n case) ───────────────────────────────


def _facts(score: dict, start: float) -> PlanFacts:
    return PlanFacts(
        orders={}, subcontract_lateness={}, setups=SetupSummary(1, 30.0),
        score=score, signature="", anticipation=((("L", None), start, start + 90.0),),
    )


def _key(facts: PlanFacts) -> tuple:
    return improvement_key(facts, transfers=0, changed_lots=0, displacement_min=0.0)


def test_lot_tardiness_gain_does_not_buy_a_later_plan():
    """rev90n: lot total tardiness 69 -> 68 with the same 11 late orders and
    58 order days late made a delivery 536 min later. Per order the delivery
    is equal, so the anticipation decides and the move is refused."""

    reference = _key(_facts(_score(orders_late=11, order_late_days=58.0,
                                   total_tardiness=69), 0.0))
    candidate = _key(_facts(_score(orders_late=11, order_late_days=58.0,
                                   total_tardiness=68), 536.0))

    assert candidate[0] == reference[0]
    assert not improvement_better(candidate, reference)
    assert regresses_reference(candidate, reference)


def test_an_order_delivered_earlier_still_ranks_first():
    reference = _key(_facts(_score(orders_late=11, order_late_days=58.0), 0.0))
    candidate = _key(_facts(_score(orders_late=11, order_late_days=57.0), 536.0))

    assert improvement_better(candidate, reference)
    assert not regresses_reference(candidate, reference)


# ── Plan facts read orders from the shared readiness ─────────────────────


def _op(op_id: str, sku: str, tool: str, demand: dict[int, int]) -> EOp:
    d = [0] * 8
    for day, qty in demand.items():
        d[day] = qty
    return EOp(
        id=op_id, sku=sku, client="CLI", designation=sku, m="M1", t=tool,
        pH=100.0, sH=0.5, operators=1, eco_lot=0, alt=None, stk=0,
        backlog=0, d=d, oee=1.0, wip=0,
    )


def _data(ops, demands) -> tuple[EngineData, FactoryConfig]:
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=ops,
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[],
        client_demands=demands,
        workdays=[f"2026-10-{day:02d}" for day in (5, 6, 7, 8, 9, 12, 13, 14)],
        n_days=8,
    )
    return data, config


def test_plan_facts_measure_fungible_orders_not_lots():
    """Two lots of one SKU: the later lot made first serves the first
    order, so a lot is late while no order is."""

    data, config = _data(
        [_op("OP-A", "A", "TA", {3: 100, 5: 100})],
        {"A": [ClientDemandEntry("X", "A", 3, "", 100, -100),
               ClientDemandEntry("X", "A", 5, "", 100, -100)]},
    )
    lots = [
        Lot("LA1", "OP-A", "TA", "M1", None, 100, 60, 30, 3, False, sku="A"),
        Lot("LA2", "OP-A", "TA", "M1", None, 100, 60, 30, 5, False, sku="A"),
    ]
    segments = [
        Segment("LA2", "R2", "M1", "TA", 2, 420, 510, "A", 100, 60, 30, sku="A"),
        Segment("LA1", "R1", "M1", "TA", 4, 420, 510, "A", 100, 60, 30, sku="A"),
    ]
    score = compute_score(segments, lots, data, config=config, include_operational_audit=False)
    facts = plan_facts(segments, lots, data, score)

    assert score["tardy_count"] == 1
    assert facts.score["orders_late"] == 0
    assert facts.score["order_late_days"] == 0
    assert "orders_late" not in score  # the caller's score is not mutated


# ── Neighbourhood: the audit's priority rotations ────────────────────────


@pytest.fixture
def inverted_plan():
    data, config = _data(
        [_op("OP-A", "A", "TA", {5: 100}), _op("OP-B", "B", "TB", {6: 100})],
        {"A": [ClientDemandEntry("X", "A", 5, "", 100, -100)],
         "B": [ClientDemandEntry("Y", "B", 6, "", 100, -100)]},
    )
    lots = [
        Lot("LA", "OP-A", "TA", "M1", None, 100, 60, 30, 5, False, sku="A"),
        Lot("LB", "OP-B", "TB", "M1", None, 100, 60, 30, 6, False, sku="B"),
    ]
    # The less urgent B runs first although A was released in time.
    segments = [
        Segment("LB", "RB", "M1", "TB", 3, 420, 510, "A", 100, 60, 30, sku="B"),
        Segment("LA", "RA", "M1", "TA", 4, 420, 510, "A", 100, 60, 30, sku="A"),
    ]
    return segments, lots, data, config


def test_priority_rotation_finds_the_audit_inversion(inverted_plan):
    segments, lots, data, config = inverted_plan
    assert find_output_priority_anomalies(segments, lots, data)
    rotation = [g for g in default_generators(data, config) if g.name == "priority_rotation"]

    improved, _lots, report = improve_plan(segments, lots, data, config, generators=rotation)

    assert report["accepted_by_scope"] == {"priority_rotation": 1}
    first = min(improved, key=lambda s: (s.day_idx, s.start_min))
    assert first.lot_id == "LA"
    assert not find_output_priority_anomalies(improved, lots, data)


def test_priority_rotation_is_in_the_default_cycle(inverted_plan):
    segments, lots, data, config = inverted_plan
    names = [g.name for g in default_generators(data, config)]

    assert names[:3] == ["earliest_legal", "priority_rotation", "alternative_anticipation"]


def test_priority_rotation_proposes_nothing_without_inversions(inverted_plan):
    segments, lots, data, config = inverted_plan
    ordered = [
        Segment("LA", "RA", "M1", "TA", 3, 420, 510, "A", 100, 60, 30, sku="A"),
        Segment("LB", "RB", "M1", "TB", 4, 420, 510, "A", 100, 60, 30, sku="B"),
    ]
    rotation = next(g for g in default_generators(data, config) if g.name == "priority_rotation")

    assert list(rotation.propose(ordered, lots)) == []


def test_priority_order_becoming_never_ready_is_never_an_improvement():
    # Review 11/10/2026: a priority order 30 days late must not "improve" into
    # one that is never ready (never-ready days are not summed).
    from types import SimpleNamespace

    from backend.scheduler.priority import delivery_improves, order_delivery_metrics

    priorities = {"A": 5}
    late = order_delivery_metrics({("A", 1): SimpleNamespace(tardiness=30.0)}, priorities)
    never = order_delivery_metrics({("A", 1): SimpleNamespace(tardiness=float("inf"))}, priorities)
    base = {"otd_d": 90.0, "otd_d_failures": 1, "tardy_count": 1, "hard_violations": 0}
    assert never["priority_orders_unready"] == 1
    assert not delivery_improves({**base, **never}, {**base, **late})
    assert delivery_improves({**base, **late}, {**base, **never})
