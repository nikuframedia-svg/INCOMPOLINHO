from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.gates import build_gate_report
from backend.scheduler.operational_audit import build_operational_audit
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, MachineInfo


def _lot(lot_id: str, rupture: int, tool: str = "T1") -> Lot:
    return Lot(
        id=lot_id,
        op_id=lot_id,
        tool_id=tool,
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=0,
        edd=rupture,
        is_twin=False,
        original_edd=rupture,
    )


def _segment(
    lot_id: str,
    day: int,
    start: int,
    *,
    tool: str = "T1",
    run_id: str | None = None,
    blockers: list[str] | None = None,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=run_id or f"RUN-{lot_id}",
        machine_id="M1",
        tool_id=tool,
        day_idx=day,
        start_min=start,
        end_min=start + 60,
        shift="A",
        qty=100,
        prod_min=60,
        left_shift_blockers=blockers or [],
    )


def _data() -> EngineData:
    return EngineData(
        ops=[],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-09-{day:02d}" for day in range(1, 21)],
        n_days=20,
        holidays=[],
    )


def test_audit_does_not_trust_stale_left_shift_annotations():
    lot = _lot("L1", 10)
    segments = [
        _segment(
            "L1",
            7,
            420,
            blockers=[
                "left_shift_available",
                "left_shift_available|day=5|interval=07:00-08:00",
            ],
        ),
        _segment("L1", 7, 480),
    ]

    audit = build_operational_audit(segments, [lot], _data())

    assert audit["left_shift_opportunities"] == 0
    assert audit["left_shift_detail"] == []


def test_audit_detects_less_urgent_lot_inside_urgent_campaign():
    urgent = _lot("URGENT", 8)
    later = _lot("LATER", 12)
    segments = [
        _segment("URGENT", 3, 420),
        _segment("LATER", 4, 420),
        _segment("URGENT", 5, 420),
    ]

    audit = build_operational_audit(segments, [urgent, later], _data())

    assert audit["lower_priority_campaign_interruptions"] == 1
    assert audit["campaign_interruption_detail"][0]["blocking_lot_id"] == "LATER"


def test_audit_reports_priority_order_anomaly_without_making_it_physical():
    urgent = _lot("URGENT", 8, tool="T2")
    later = _lot("LATER", 12)
    segments = [
        _segment("LATER", 3, 420),
        _segment("URGENT", 4, 420, tool="T2"),
    ]

    audit = build_operational_audit(segments, [urgent, later], _data())

    assert audit["priority_order_anomalies"] == 1
    assert audit["priority_order_detail"][0]["urgent_lot_id"] == "URGENT"
    assert audit["priority_order_detail"][0]["verification_status"] == "permutable"
    assert audit["avoidable_priority_order_anomalies"] == 1


def test_audit_does_not_block_priority_pairs_with_frozen_history():
    from backend.scheduler.canonical import preserved_lot_proofs

    urgent = _lot("URGENT", 8, tool="T2")
    historical = _lot("HISTORICAL", 12)
    segments = [
        _segment("HISTORICAL", 0, 420),
        _segment("URGENT", 1, 420, tool="T2"),
    ]
    data = _data()
    data.preserved_lot_proofs = preserved_lot_proofs(segments[:1], [historical])

    audit = build_operational_audit(
        segments,
        [urgent, historical],
        data,
    )

    assert audit["priority_order_anomalies"] == 1
    assert audit["priority_order_detail"][0]["verification_status"] == (
        "historical_locked"
    )
    assert audit["avoidable_priority_order_anomalies"] == 0


def test_audit_does_not_block_unproven_neutral_counterfactual(monkeypatch):
    monkeypatch.setattr(
        "backend.scheduler.operational_audit.classify_priority_order_anomalies",
        lambda *_args, **_kwargs: [
            {
                "verification_status": "counterfactual_required",
                "blocking_reason": "counterfactual_did_not_reduce_priority_anomalies",
            }
        ],
    )

    audit = build_operational_audit([], [], _data())

    assert audit["priority_order_anomalies"] == 1
    assert audit["avoidable_priority_order_anomalies"] == 0


def test_priority_audit_uses_customer_date_when_rupture_ties():
    urgent = _lot("URGENT", 10, tool="T2")
    urgent.delivery_day = 8
    later = _lot("LATER", 10)
    later.delivery_day = 12
    segments = [
        _segment("LATER", 3, 420),
        _segment("URGENT", 4, 420, tool="T2"),
    ]

    audit = build_operational_audit(segments, [urgent, later], _data())

    assert audit["priority_order_anomalies"] == 1
    assert audit["priority_order_detail"][0]["urgent_lot_id"] == "URGENT"


def test_priority_anomaly_does_not_treat_the_lower_priority_run_as_its_own_blocker():
    urgent = _lot("URGENT", 8, tool="T2")
    later = _lot("LATER", 12)
    segments = [
        _segment("LATER", 3, 420),
        _segment(
            "URGENT",
            4,
            420,
            tool="T2",
            blockers=[
                "blocked_by_machine_busy",
                "blocked_by_machine_busy|day=3|lot=LATER|machine=M1",
            ],
        ),
    ]

    detail = build_operational_audit(segments, [urgent, later], _data())[
        "priority_order_detail"
    ][0]

    assert detail["verification_status"] == "permutable"
    assert detail["blocking_reason"] is None
    assert detail["blocking_reasons"] == []


def test_priority_repair_prefers_earlier_rupture_over_unweighted_time_cost():
    from backend.scheduler.priority_normalization import repair_priority_inversions
    from backend.scheduler.validation import validate_plan

    urgent = _lot("URGENT", 8, tool="T2")
    urgent.prod_min = 60
    urgent.setup_min = 30
    later = _lot("LATER", 12, tool="T1")
    later.prod_min = 300
    later.setup_min = 30
    segments = [
        Segment(
            lot_id="LATER",
            run_id="RUN-LATER",
            machine_id="M1",
            tool_id="T1",
            day_idx=7,
            start_min=420,
            end_min=750,
            shift="A",
            qty=100,
            prod_min=300,
            setup_min=30,
            run_setup_min=30,
            edd=12,
        ),
        Segment(
            lot_id="URGENT",
            run_id="RUN-URGENT",
            machine_id="M1",
            tool_id="T2",
            day_idx=7,
            start_min=750,
            end_min=840,
            shift="A",
            qty=100,
            prod_min=60,
            setup_min=30,
            run_setup_min=30,
            edd=8,
        ),
    ]
    data = _data()
    config = FactoryConfig(
        machines={"M1": MachineConfig("M1", "Grandes")},
        setup_crews_by_group={"Grandes": 1},
    )
    before = compute_score(
        segments,
        [urgent, later],
        data,
        config=config,
        include_operational_audit=False,
    )

    repaired = repair_priority_inversions(segments, [urgent, later], data, config)
    after = compute_score(
        repaired,
        [urgent, later],
        data,
        config=config,
        include_operational_audit=False,
    )

    first_productive = min(
        (segment for segment in repaired if segment.prod_min > 0),
        key=lambda segment: (segment.day_idx, segment.start_min),
    )
    assert first_productive.lot_id == "URGENT"
    assert after["production_time_cost"] > before["production_time_cost"]
    assert after["otd"] == before["otd"]
    assert after["otd_d"] == before["otd_d"]
    assert validate_plan(repaired, data, config, lots=[urgent, later]) == []


def test_audit_detects_partial_internal_continuation_gap():
    lot = _lot("L1", 10)
    lot.qty = 600
    lot.prod_min = 600
    segments = [
        Segment(
            lot_id="L1",
            run_id="RUN-L1",
            machine_id="M1",
            tool_id="T1",
            day_idx=7,
            start_min=420,
            end_min=520,
            shift="A",
            qty=100,
            prod_min=100,
        ),
        Segment(
            lot_id="L1",
            run_id="RUN-L1",
            machine_id="M1",
            tool_id="T1",
            day_idx=7,
            start_min=670,
            end_min=1170,
            shift="B",
            qty=500,
            prod_min=500,
            is_continuation=True,
        ),
    ]

    audit = build_operational_audit(segments, [lot], _data())

    assert audit["left_shift_opportunities"] == 1
    detail = audit["left_shift_detail"][0]
    assert detail["gap_day"] == 7
    assert detail["gap_start_min"] == 520
    assert detail["gap_end_min"] == 670
    assert detail["movable_prod_min"] == 150
    assert detail["source_day"] == 7
    assert detail["source_start_min"] == 670


def test_gate_blocks_candidate_with_avoidable_partial_gap():
    lot = _lot("L1", 10)
    lot.qty = 330
    lot.prod_min = 330
    data = _data()
    config = FactoryConfig(
        machines={"M1": MachineConfig("M1", "Grandes")},
    )
    segments = [
        Segment(
            lot_id="L1",
            run_id="RUN-L1",
            machine_id="M1",
            tool_id="T1",
            day_idx=7,
            start_min=420,
            end_min=520,
            shift="A",
            qty=100,
            prod_min=100,
        ),
        Segment(
            lot_id="L1",
            run_id="RUN-L1",
            machine_id="M1",
            tool_id="T1",
            day_idx=7,
            start_min=670,
            end_min=900,
            shift="B",
            qty=230,
            prod_min=230,
            is_continuation=True,
        ),
    ]

    score = compute_score(segments, [lot], data, config=config)
    report = build_gate_report(segments, [lot], score, data, config)

    assert report["metrics"]["left_shift_opportunities"] == 1
    assert report["operational_gate_passed"] is False
    assert report["apply_decision"] == "approval_required"
    assert report["requires_approval"] is True
    assert report["status"] == "best_effort"


def _gap_case():
    lot = _lot("L1", 10)
    lot.qty = 600
    lot.prod_min = 600
    segments = [
        Segment(lot_id="L1", run_id="RUN-L1", machine_id="M1", tool_id="T1",
                day_idx=7, start_min=420, end_min=520, shift="A", qty=100, prod_min=100),
        Segment(lot_id="L1", run_id="RUN-L1", machine_id="M1", tool_id="T1",
                day_idx=7, start_min=670, end_min=1170, shift="B", qty=500, prod_min=500,
                is_continuation=True),
    ]
    return segments, [lot]


def test_gap_before_historical_lot_is_explained_not_actionable():
    from backend.scheduler.canonical import preserved_lot_proofs

    segments, lots = _gap_case()
    data = _data()
    data.preserved_lot_proofs = preserved_lot_proofs(segments, lots)

    audit = build_operational_audit(segments, lots, data)

    assert audit["left_shift_opportunities"] == 0
    assert [item["protection"] for item in audit["protected_left_shift_detail"]] == [
        "historical_lot_locked",
    ]


def test_gap_before_anchored_lot_is_explained_not_actionable():
    from backend.types import PlanAnchor

    segments, lots = _gap_case()
    data = _data()
    data.plan_anchors = [PlanAnchor("L1", "M1", "2026-09-08T07:00")]

    audit = build_operational_audit(segments, lots, data)

    assert audit["left_shift_opportunities"] == 0
    assert audit["protected_left_shift_detail"][0]["protection"] == "manual_anchor"
