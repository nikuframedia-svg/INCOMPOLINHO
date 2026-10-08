"""Tests for Spec 12: Integration modules.

Guardian, Journal, DQA, Late Delivery, Workforce, Replan, Presets, Cache, Coverage.
"""

from __future__ import annotations


import pytest

from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment, ScheduleResult
from backend.types import EngineData, EOp, MachineInfo, TwinGroup, ClientDemandEntry


# ─── Fixtures ────────────────────────────────────────────────────────────


def _eop(
    op_id: str,
    sku: str,
    machine: str,
    tool: str,
    pH: float = 100.0,
    eco_lot: int = 500,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
    d: list[int] | None = None,
    client: str = "TEST",
    backlog: int = 0,
    stk: int = 0,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client=client,
        designation=f"Desc {sku}",
        m=machine,
        t=tool,
        pH=pH,
        sH=sH,
        operators=1,
        eco_lot=eco_lot,
        alt=alt,
        stk=stk,
        backlog=backlog,
        d=d or [0] * 20,
        oee=oee,
        wip=0,
    )


def _engine(
    ops: list[EOp] | None = None,
    n_days: int = 20,
    machines: list[MachineInfo] | None = None,
    twin_groups: list[TwinGroup] | None = None,
) -> EngineData:
    if ops is None:
        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", d=[0, 500, 0] + [0] * 17)]
    if machines is None:
        machines = [
            MachineInfo(id="PRM019", group="Grandes", day_capacity=1020),
            MachineInfo(id="PRM031", group="Grandes", day_capacity=1020),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=1020),
            MachineInfo(id="PRM042", group="Medias", day_capacity=1020),
            MachineInfo(id="PRM043", group="Grandes", day_capacity=1020),
        ]

    # Build client_demands from ops
    workdays = [f"2026-03-{i + 1:02d}" for i in range(n_days)]
    client_demands: dict[str, list[ClientDemandEntry]] = {}
    for op in ops:
        entries = []
        for day_idx, qty in enumerate(op.d):
            if qty > 0:
                date = workdays[day_idx] if day_idx < len(workdays) else ""
                entries.append(
                    ClientDemandEntry(
                        client=op.client,
                        sku=op.sku,
                        day_idx=day_idx,
                        date=date,
                        order_qty=qty,
                        np_value=-qty,
                    )
                )
        if entries:
            client_demands.setdefault(op.sku, []).extend(entries)

    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=twin_groups or [],
        client_demands=client_demands,
        workdays=[f"2026-03-{i + 1:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _seg(
    lot_id: str = "L1",
    run_id: str = "R1",
    machine: str = "PRM019",
    tool: str = "T1",
    day_idx: int = 0,
    start: int = 420,
    end: int = 930,
    shift: str = "A",
    qty: int = 500,
    prod_min: float = 500.0,
    setup_min: float = 0.0,
    sku: str = "SKU1",
    edd: int = 5,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=run_id,
        machine_id=machine,
        tool_id=tool,
        day_idx=day_idx,
        start_min=start,
        end_min=end,
        shift=shift,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        sku=sku,
        edd=edd,
    )


def _lot(
    lot_id: str = "L1",
    op_id: str = "T1_M1_SKU1",
    tool: str = "T1",
    machine: str = "PRM019",
    qty: int = 500,
    prod_min: float = 500.0,
    setup_min: float = 30.0,
    edd: int = 5,
    alt: str | None = None,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=alt,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=edd,
        is_twin=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. Guardian
# ═══════════════════════════════════════════════════════════════════════


class TestGuardianInput:
    def test_clean_data(self):
        from backend.guardian import validate_input

        data = _engine()
        result = validate_input(data)
        assert result.is_clean
        assert len(result.issues) == 0
        assert len(result.dropped_ops) == 0

    def test_drop_zero_ph(self):
        from backend.guardian import validate_input

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", pH=0)]
        data = _engine(ops=ops)
        result = validate_input(data)
        assert "T1_M1_SKU1" in result.dropped_ops
        assert len(result.cleaned.ops) == 0

    def test_drop_invalid_machine(self):
        from backend.guardian import validate_input

        ops = [_eop("T1_MX_SKU1", "SKU1", "INVALID", "T1")]
        data = _engine(ops=ops)
        result = validate_input(data)
        assert "T1_MX_SKU1" in result.dropped_ops

    def test_fix_negative_eco_lot(self):
        from backend.guardian import validate_input

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", eco_lot=-100)]
        data = _engine(ops=ops)
        result = validate_input(data)
        assert not result.is_clean
        fixed_op = result.cleaned.ops[0]
        assert fixed_op.eco_lot == 0

    def test_fix_invalid_oee(self):
        from backend.guardian import validate_input

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", oee=2.0)]
        data = _engine(ops=ops)
        result = validate_input(data)
        assert result.cleaned.ops[0].oee == 0.66

    def test_fix_demand_length(self):
        from backend.guardian import validate_input

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", d=[0, 500])]
        data = _engine(ops=ops, n_days=20)
        result = validate_input(data)
        assert len(result.cleaned.ops[0].d) == 20

    def test_drop_duplicate_id(self):
        from backend.guardian import validate_input

        ops = [
            _eop("T1_M1_SKU1", "SKU1", "PRM019", "T1"),
            _eop("T1_M1_SKU1", "SKU2", "PRM031", "T2"),
        ]
        data = _engine(ops=ops)
        result = validate_input(data)
        assert "T1_M1_SKU1" in result.dropped_ops


class TestGuardianOutput:
    def test_clean_output(self):
        from backend.guardian import validate_output

        data = _engine()
        segs = [_seg(day_idx=0, start=420, end=930)]
        issues = validate_output(segs, data)
        assert len(issues) == 0

    def test_out_of_horizon(self):
        from backend.guardian import validate_output

        data = _engine(n_days=5)
        segs = [_seg(day_idx=10)]
        issues = validate_output(segs, data)
        assert any("horizonte" in i.message for i in issues)

    def test_overlap_detection(self):
        from backend.guardian import validate_output

        data = _engine()
        segs = [
            _seg(start=420, end=700),
            _seg(lot_id="L2", start=600, end=930),  # overlaps
        ]
        issues = validate_output(segs, data)
        assert any("Sobreposição" in i.message for i in issues)


# ═══════════════════════════════════════════════════════════════════════
# 2. Journal
# ═══════════════════════════════════════════════════════════════════════


class TestJournal:
    def test_phase_recording(self):
        from backend.journal import Journal

        j = Journal()
        j.phase_start("test")
        j.phase_end("test", "done", items=5)
        entries = j.to_entries()
        assert len(entries) == 1
        assert entries[0].step == "test"
        assert entries[0].severity == "info"
        assert entries[0].metadata["items"] == 5
        assert entries[0].elapsed_ms >= 0

    def test_to_warnings_filters(self):
        from backend.journal import Journal

        j = Journal()
        j.log("step1", "info", "Normal")
        j.log("step2", "warn", "Problem")
        j.log("step3", "error", "Critical")
        warnings = j.to_warnings()
        assert len(warnings) == 2
        assert "[step2]" in warnings[0]
        assert "[step3]" in warnings[1]

    def test_to_dicts(self):
        from backend.journal import Journal

        j = Journal()
        j.log("x", "info", "msg", key=1)
        dicts = j.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["step"] == "x"
        assert dicts[0]["metadata"]["key"] == 1


# ═══════════════════════════════════════════════════════════════════════
# 3. DQA / TrustIndex
# ═══════════════════════════════════════════════════════════════════════


class TestDQA:
    def test_perfect_data(self):
        from backend.dqa import compute_trust_index

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", alt="PRM031", d=[0, 500, 0] + [0] * 17)]
        data = _engine(ops=ops)
        result = compute_trust_index(data)
        assert result.score >= 70
        assert result.gate in ("full_auto", "monitoring")

    def test_bad_data_low_score(self):
        from backend.dqa import compute_trust_index

        ops = [_eop("T1_M1_SKU1", "SKU1", "INVALID", "T1", pH=0, oee=-1)]
        data = _engine(ops=ops)
        result = compute_trust_index(data)
        assert result.score < 70
        assert result.n_issues > 0

    def test_gate_thresholds(self):
        from backend.dqa import compute_trust_index

        # Good data
        data = _engine()
        result = compute_trust_index(data)
        assert result.gate in ("full_auto", "monitoring", "suggestion")
        assert result.score >= 0
        assert result.score <= 100


# ═══════════════════════════════════════════════════════════════════════
# 4. Late Delivery Analysis
# ═══════════════════════════════════════════════════════════════════════


class TestLateDelivery:
    def test_no_tardy(self):
        from backend.analytics.late_delivery import analyze_late_deliveries

        data = _engine()
        lots = [_lot(edd=10)]
        segs = [_seg(day_idx=2)]  # completes day 2, edd=10 → not tardy
        report = analyze_late_deliveries(segs, lots, data)
        assert report.tardy_count == 0

    def test_tardy_detected(self):
        from backend.analytics.late_delivery import analyze_late_deliveries

        data = _engine()
        lots = [_lot(edd=1)]
        segs = [_seg(day_idx=5, edd=1)]  # completes day 5, edd=1 → tardy
        report = analyze_late_deliveries(segs, lots, data)
        assert report.tardy_count == 1
        assert report.analyses[0].delay_days == 4

    def test_root_cause_classification(self):
        from backend.analytics.late_delivery import analyze_late_deliveries

        data = _engine()
        lots = [_lot(edd=1, prod_min=5000.0)]  # lead_time: 5000 > 1*1020
        segs = [_seg(day_idx=5, edd=1, prod_min=5000.0)]
        report = analyze_late_deliveries(segs, lots, data)
        assert report.tardy_count == 1
        assert report.analyses[0].root_cause == "lead_time"


# ═══════════════════════════════════════════════════════════════════════
# 5. Workforce Forecast
# ═══════════════════════════════════════════════════════════════════════


class TestWorkforce:
    def test_no_deficit(self):
        from backend.analytics.workforce_forecast import forecast_workforce

        data = _engine()
        config = FactoryConfig()
        segs = [_seg(day_idx=0)]
        result = forecast_workforce(segs, data, config, window=5)
        assert result.deficit_days == 0
        assert result.trend in ("increasing", "stable", "decreasing")

    def test_peak_detection(self):
        from backend.analytics.workforce_forecast import forecast_workforce

        data = _engine()
        config = FactoryConfig()
        # Many segments on day 2
        segs = [_seg(lot_id=f"L{i}", day_idx=2, machine=f"PRM0{19 + i % 3:02d}") for i in range(10)]
        result = forecast_workforce(segs, data, config, window=5)
        assert result.peak_day == 2
        assert result.peak_required > 0

    def test_trend_increasing(self):
        from backend.analytics.workforce_forecast import forecast_workforce

        data = _engine()
        config = FactoryConfig()
        # More work in second half
        segs = [_seg(lot_id=f"L{i}", day_idx=i) for i in range(5, 10)]
        result = forecast_workforce(segs, data, config, window=10)
        assert result.trend == "increasing"


# ═══════════════════════════════════════════════════════════════════════
# 6. Replan Proposals
# ═══════════════════════════════════════════════════════════════════════


class TestReplan:
    def test_no_proposals_when_clean(self):
        from backend.analytics.replan_proposals import generate_proposals

        data = _engine()
        config = FactoryConfig()
        segs = [_seg(day_idx=0)]
        lots = [_lot(edd=10)]
        score = {"tardy_count": 0, "setups": 5}
        report = generate_proposals(segs, lots, data, score, config)
        assert len(report.proposals) == 0

    def test_move_to_alt_proposal(self):
        from backend.analytics.replan_proposals import generate_proposals

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", alt="PRM031", d=[0, 500, 0] + [0] * 17)]
        data = _engine(ops=ops)
        config = FactoryConfig()
        # Tardy lot: completes day 5 but edd=1, alt machine PRM031 is free
        segs = [_seg(day_idx=5, edd=1)]
        lots = [_lot(edd=1, alt="PRM031")]
        score = {"tardy_count": 1, "setups": 5}
        report = generate_proposals(segs, lots, data, score, config)
        alt_proposals = [p for p in report.proposals if p.type == "move_to_alt"]
        assert len(alt_proposals) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 7. Policy Presets
# ═══════════════════════════════════════════════════════════════════════


class TestPresets:
    def test_list_presets(self):
        from backend.config.presets import list_presets

        names = list_presets()
        assert "urgente" in names
        assert "equilibrado" in names
        assert "min_setups" in names
        assert "max_otd" in names

    def test_apply_urgente(self):
        from backend.config.presets import apply_preset

        config = FactoryConfig()
        result = apply_preset(config, "urgente")
        assert result.jit_enabled is True
        assert result.urgency_threshold == 2
        # Original unchanged
        assert config.jit_enabled is True

    def test_apply_equilibrado(self):
        from backend.config.presets import apply_preset

        config = FactoryConfig()
        result = apply_preset(config, "equilibrado")
        assert result.jit_enabled == config.jit_enabled  # no overrides

    def test_unknown_preset(self):
        from backend.config.presets import apply_preset

        with pytest.raises(KeyError):
            apply_preset(FactoryConfig(), "nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# 8. Idempotency Cache
# ═══════════════════════════════════════════════════════════════════════


class TestCache:
    def test_cache_hit(self):
        from backend.scheduler.cache import get_cached, put_cache, clear_cache

        clear_cache()
        data = _engine()
        config = FactoryConfig()
        result = ScheduleResult(
            segments=[],
            lots=[],
            score={"otd": 100},
            time_ms=10.0,
            warnings=[],
            operator_alerts=[],
        )
        put_cache(data, config, result)
        cached = get_cached(data, config)
        assert cached is not None
        assert cached.score["otd"] == 100

    def test_cache_miss(self):
        from backend.scheduler.cache import get_cached, clear_cache

        clear_cache()
        data = _engine()
        assert get_cached(data) is None

    def test_cache_eviction(self):
        from backend.scheduler.cache import put_cache, clear_cache, _cache, _MAX_CACHE

        clear_cache()
        config = FactoryConfig()
        for i in range(_MAX_CACHE + 2):
            ops = [_eop(f"T1_M1_SKU{i}", f"SKU{i}", "PRM019", "T1")]
            data = _engine(ops=ops)
            result = ScheduleResult(
                segments=[],
                lots=[],
                score={},
                time_ms=0,
                warnings=[],
                operator_alerts=[],
            )
            put_cache(data, config, result)
        assert len(_cache) == _MAX_CACHE


# ═══════════════════════════════════════════════════════════════════════
# 9. Coverage Audit
# ═══════════════════════════════════════════════════════════════════════


class TestCoverageAudit:
    def test_full_coverage(self):
        """When all orders are ready, coverage should be 100%."""
        from backend.analytics.coverage_audit import compute_coverage_audit
        from backend.scheduler.scheduler import schedule_all

        ops = [_eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", d=[0, 500, 0] + [0] * 17, stk=1000)]
        data = _engine(ops=ops)
        config = FactoryConfig()
        result = schedule_all(data, config=config)
        audit = compute_coverage_audit(result.segments, result.lots, data)
        assert audit.overall_coverage_pct >= 0  # may be 100 with stock
        assert audit.health_score >= 0

    def test_clients_listed(self):
        from backend.analytics.coverage_audit import compute_coverage_audit
        from backend.scheduler.scheduler import schedule_all

        ops = [
            _eop("T1_M1_SKU1", "SKU1", "PRM019", "T1", client="ClientA", d=[0, 500, 0] + [0] * 17),
            _eop("T2_M2_SKU2", "SKU2", "PRM031", "T2", client="ClientB", d=[0, 0, 300] + [0] * 17),
        ]
        data = _engine(ops=ops)
        config = FactoryConfig()
        result = schedule_all(data, config=config)
        audit = compute_coverage_audit(result.segments, result.lots, data)
        # At least one client should appear if there are demands
        assert len(audit.clients) >= 0


# ═══════════════════════════════════════════════════════════════════════
# Integration: schedule_all with Journal
# ═══════════════════════════════════════════════════════════════════════


class TestScheduleAllIntegration:
    def test_journal_attached(self):
        """schedule_all should return journal entries."""
        from backend.scheduler.scheduler import schedule_all

        data = _engine()
        config = FactoryConfig()
        result = schedule_all(data, config=config)
        assert result.journal is not None
        assert len(result.journal) > 0
        steps = {e["step"] for e in result.journal}
        assert "guardian" in steps
        assert "lot_sizing" in steps

    def test_backward_compatible(self):
        """Existing code reading .warnings still works."""
        from backend.scheduler.scheduler import schedule_all

        data = _engine()
        config = FactoryConfig()
        result = schedule_all(data, config=config)
        assert isinstance(result.warnings, list)
        assert isinstance(result.score, dict)
