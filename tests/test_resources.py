"""Tests for backend/scheduler/resources.py — Fase 1.2 rebind."""

from __future__ import annotations

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.resources import (
    clone_run_for_machine,
    effective_oee,
    rebind_runs_to_machines,
    resolve_setup_hours,
)
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, ToolRun
from backend.types import EngineData, EOp, MachineInfo


def _eop(
    op_id: str = "T1_M1_SKU1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    d: list[int] | None = None,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client="CLIENT",
        designation="Test",
        m=machine,
        t=tool,
        pH=pH,
        sH=sH,
        operators=1,
        eco_lot=0,
        alt=alt,
        stk=0,
        backlog=0,
        d=d or [0, 0, 0, 0, 0, 0, 500, 0, 300, 0],
        oee=oee,
        wip=0,
    )


def _engine(ops: list[EOp], n_days: int = 10) -> EngineData:
    machine_ids: list[str] = []
    for op in ops:
        if op.m not in machine_ids:
            machine_ids.append(op.m)
        if op.alt and op.alt not in machine_ids:
            machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i + 2:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _config_with_machines(*mids: str, **kwargs) -> FactoryConfig:
    c = FactoryConfig(**kwargs)
    for mid in mids:
        c.machines[mid] = MachineConfig(id=mid, group="Grandes")
    return c


def _runs_for(engine: EngineData, config: FactoryConfig) -> list[ToolRun]:
    lots = create_lots(engine, config=config)
    return create_tool_runs(lots, config=config)


class TestResolvers:
    def test_setup_fallback_chain(self):
        c = _config_with_machines("M1", "M2")
        c.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 1.5}]
        assert resolve_setup_hours("SKU1", "M2", 0.5, c) == 1.5
        assert resolve_setup_hours("SKU1", "M1", 0.5, c) == 0.5  # per-tool fallback
        assert resolve_setup_hours("SKU9", "M2", 0.0, c) == 0.0
        assert resolve_setup_hours("SKU9", "M2", None, c) == c.default_setup_hours

    def test_effective_oee_chain(self):
        c = _config_with_machines("M1", "M2")
        c.machines["M2"].oee = 0.9
        op = _eop()
        assert effective_oee(op, "M1", c) == 0.66  # op master value
        assert effective_oee(op, "M2", c) == 0.9  # machine override
        op.oee_source = "whatif"
        op.oee = 0.5
        assert effective_oee(op, "M2", c) == 0.5  # what-if wins over machine

    def test_effective_oee_default_when_op_zero(self):
        c = _config_with_machines("M1")
        op = _eop(oee=0.0)
        assert effective_oee(op, "M1", c) == c.oee_default


class TestRebind:
    def test_noop_without_machine_dependent_config(self):
        engine = _engine([_eop()])
        config = _config_with_machines("M1")
        runs = _runs_for(engine, config)
        before = [(r.setup_min, r.total_prod_min, r.total_min) for r in runs]
        rebind_runs_to_machines({"M1": runs}, engine, config)
        after = [(r.setup_min, r.total_prod_min, r.total_min) for r in runs]
        assert before == after

    def test_override_applied_per_assigned_machine(self):
        engine = _engine([_eop(alt="M2")])
        config = _config_with_machines("M1", "M2")
        config.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 2.0}]

        runs_primary = _runs_for(engine, config)
        rebind_runs_to_machines({"M1": runs_primary}, engine, config)
        assert runs_primary[0].setup_min == 0.5 * 60.0  # per-tool value on M1

        runs_alt = _runs_for(engine, config)
        rebind_runs_to_machines({"M2": runs_alt}, engine, config)
        assert runs_alt[0].setup_min == 2.0 * 60.0
        assert runs_alt[0].lots[0].setup_min == 2.0 * 60.0
        assert runs_alt[0].total_min == runs_alt[0].setup_min + runs_alt[0].total_prod_min

    def test_per_machine_oee_scales_prod_min(self):
        engine = _engine([_eop(alt="M2")])
        config = _config_with_machines("M1", "M2")
        config.machines["M2"].oee = 0.9

        runs = _runs_for(engine, config)
        base_prod = runs[0].total_prod_min
        rebind_runs_to_machines({"M2": runs}, engine, config)
        # Higher OEE → less production time, scaled by 0.66/0.9
        assert runs[0].total_prod_min < base_prod
        expected = base_prod * (0.66 / 0.9)
        assert abs(runs[0].total_prod_min - expected) < 0.01

    def test_rebind_idempotent_and_absolute(self):
        engine = _engine([_eop(alt="M2")])
        config = _config_with_machines("M1", "M2")
        config.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 2.0}]
        config.machines["M2"].oee = 0.9

        runs_a = _runs_for(engine, config)
        rebind_runs_to_machines({"M2": runs_a}, engine, config)
        rebind_runs_to_machines({"M2": runs_a}, engine, config)  # twice == once
        runs_b = _runs_for(engine, config)
        rebind_runs_to_machines({"M1": runs_b}, engine, config)  # bind M1 first
        rebind_runs_to_machines({"M2": runs_b}, engine, config)  # then M2

        assert runs_a[0].setup_min == runs_b[0].setup_min == 120.0
        assert abs(runs_a[0].total_prod_min - runs_b[0].total_prod_min) < 1e-9

    def test_twin_lot_uses_max_of_both_skus(self):
        op_a = _eop(op_id="T1_M1_SKA", sku="SKA")
        op_b = _eop(op_id="T1_M1_SKB", sku="SKB", pH=50.0)
        engine = _engine([op_a, op_b])
        config = _config_with_machines("M1")
        config.setup_overrides = [{"sku": "SKB", "machine": "M1", "hours": 1.25}]

        lot = Lot(
            id="LOT_TWIN",
            op_id=op_a.id,
            tool_id="T1",
            machine_id="M1",
            alt_machine_id=None,
            qty=600,
            prod_min=0.0,
            setup_min=30.0,
            edd=6,
            is_twin=True,
            twin_outputs=[(op_a.id, "SKA", 600), (op_b.id, "SKB", 400)],
        )
        run = ToolRun(
            id="run_T1_M1_0",
            tool_id="T1",
            machine_id="M1",
            alt_machine_id=None,
            lots=[lot],
            setup_min=30.0,
            total_prod_min=0.0,
            total_min=30.0,
            edd=6,
        )
        rebind_runs_to_machines({"M1": [run]}, engine, config)
        # Setup: max(SKA→0.5h per-tool, SKB→1.25h override) = 1.25h
        assert lot.setup_min == 1.25 * 60.0
        # Prod: max(600/(100*0.66), 400/(50*0.66)) hours → SKB slower
        expected = (400 / (50.0 * 0.66)) * 60.0
        assert abs(lot.prod_min - expected) < 0.01
        assert run.setup_min == lot.setup_min

    def test_setup_family_run_uses_max_setup_after_rebind(self):
        op_a = _eop(op_id="T1_M1_SKA", sku="SKA", sH=0.5)
        op_b = _eop(op_id="T1_M1_SKB", sku="SKB", sH=1.5)
        engine = _engine([op_a, op_b])
        config = _config_with_machines("M1")
        config.setup_families = {"T1": [["SKA", "SKB"]]}
        config.setup_overrides = [
            {"sku": "SKA", "machine": "M1", "hours": 0.5},
            {"sku": "SKB", "machine": "M1", "hours": 1.5},
        ]
        runs = _runs_for(engine, config)

        rebind_runs_to_machines({"M1": runs}, engine, config)

        assert len(runs) == 1
        assert {lot.setup_min for lot in runs[0].lots} == {30.0, 90.0}
        assert runs[0].setup_min == 90.0
        assert runs[0].total_min == runs[0].total_prod_min + 90.0

    def test_clone_does_not_mutate_original(self):
        engine = _engine([_eop(alt="M2")])
        config = _config_with_machines("M1", "M2")
        config.setup_overrides = [{"sku": "SKU1", "machine": "M2", "hours": 2.0}]

        runs = _runs_for(engine, config)
        rebind_runs_to_machines({"M1": runs}, engine, config)
        original = runs[0]
        orig_setup = original.setup_min
        orig_lot_setup = original.lots[0].setup_min

        clone = clone_run_for_machine(original, "M2", engine, config)
        assert clone.machine_id == "M2"
        assert clone.setup_min == 120.0
        assert clone.lots[0].setup_min == 120.0
        assert original.setup_min == orig_setup
        assert original.lots[0].setup_min == orig_lot_setup
        assert clone.lots[0] is not original.lots[0]


class TestEndToEnd:
    def test_schedule_all_with_override_keeps_otd(self):
        engine = _engine([_eop()])
        config = _config_with_machines("M1")
        config.setup_overrides = [{"sku": "SKU1", "machine": "M1", "hours": 1.5}]
        result = schedule_all(engine, config=config)
        assert result.score["otd"] == 100.0
        setup_segs = [s for s in result.segments if s.setup_min > 0]
        assert setup_segs
        assert all(s.setup_min == 90.0 for s in setup_segs)

    def test_schedule_all_identical_without_overrides(self):
        engine = _engine([_eop(alt="M2")])
        r1 = schedule_all(engine)
        r2 = schedule_all(engine, config=_config_with_machines("M1", "M2"))
        assert r1.score == r2.score
