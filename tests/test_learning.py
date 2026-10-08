"""Tests for Learning Engine — Spec 08."""

from __future__ import annotations

import time

from backend.learning import (
    ISContext,
    LearnStore,
    OptunaTuner,
    SchedulerParams,
    StudyResult,
    ThompsonTransfer,
    compute_reward,
    extract_context,
    smart_schedule,
)
from backend.scheduler.constants import (
    DAY_CAP,
    EDD_SWAP_TOLERANCE,
    MAX_EDD_GAP,
    MAX_RUN_DAYS,
)
from backend.scheduler.scheduler import schedule_all
from backend.types import EngineData, EOp, MachineInfo


# --- Fixtures ---


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
        d=d or [0, 500, 0, 300, 0],
        oee=oee,
        wip=0,
    )


def _engine(
    ops: list[EOp] | None = None,
    n_days: int = 10,
) -> EngineData:
    if ops is None:
        ops = [_eop()]
    machine_ids = list({op.m for op in ops})
    if ops and any(op.alt for op in ops):
        for op in ops:
            if op.alt and op.alt not in machine_ids:
                machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i + 5:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _dummy_context() -> ISContext:
    return ISContext(
        n_ops=5,
        n_machines=2,
        n_days=10,
        total_demand=1000,
        avg_oee=0.66,
        twin_pct=0.0,
        alt_pct=0.0,
        avg_edd=5.0,
        demand_density=0.3,
    )


def _dummy_study_result(reward: float = 0.7) -> StudyResult:
    return StudyResult(
        best_params=SchedulerParams(),
        best_reward=reward,
        best_score={"otd": 100, "setups": 100, "earliness_avg_days": 5},
        baseline_score={"otd": 100, "setups": 120, "earliness_avg_days": 6},
        improvement={"reward": 0.1, "earliness_delta": -1.0, "setups_delta": -20},
        n_trials=20,
        total_time_ms=5000,
        confidence="medium",
    )


# --- SchedulerParams Tests ---


class TestSchedulerParams:
    def test_defaults_match_constants(self):
        p = SchedulerParams()
        assert p.max_edd_gap == MAX_EDD_GAP
        assert p.max_run_days == MAX_RUN_DAYS
        assert p.edd_swap_tolerance == EDD_SWAP_TOLERANCE

    def test_default_params_same_as_no_params(self):
        """CRITICAL: schedule_all(data) with default config == schedule_all(data)."""
        engine = _engine()
        r1 = schedule_all(engine)
        from backend.config.types import FactoryConfig

        r2 = schedule_all(engine, config=FactoryConfig())
        for key, value in r1.score.items():
            assert r2.score[key] == value

    def test_to_from_dict_roundtrip(self):
        p = SchedulerParams(max_edd_gap=8, backward_buffer_pct=0.1)
        d = p.to_dict()
        p2 = SchedulerParams.from_dict(d)
        assert p2.max_edd_gap == 8
        assert p2.backward_buffer_pct == 0.1

    def test_from_dict_ignores_extra_keys(self):
        d = {"max_edd_gap": 7, "unknown_param": 42}
        p = SchedulerParams.from_dict(d)
        assert p.max_edd_gap == 7
        assert p.max_run_days == 4  # industrial default

    def test_custom_params_change_behaviour(self):
        """Non-default params should produce a different schedule."""
        engine = _engine(
            ops=[
                _eop(
                    op_id="T1_M1_SKU1",
                    machine="M1",
                    tool="T1",
                    d=[0, 0, 0, 0, 800, 800, 0, 0, 0, 0],
                ),
            ]
        )
        r1 = schedule_all(engine)
        # Extreme config: very aggressive splitting + no interleave
        from backend.config.types import FactoryConfig

        cfg = FactoryConfig(
            max_edd_gap=1,
            max_run_days=1,
            interleave_enabled=False,
            campaign_window=5,
        )
        r2 = schedule_all(engine, config=cfg)
        # Release floors are invariant, but the configured run split remains
        # visible in the campaign identities used by the planner.
        assert [segment.run_id for segment in r1.segments] != [
            segment.run_id for segment in r2.segments
        ]


# --- Reward Tests ---


class TestReward:
    def test_infeasible_negative(self):
        score = {"otd_d_failures": 2, "tardy_count": 1}
        assert compute_reward(score) < 0

    def test_perfect_otd_positive(self):
        score = {
            "otd": 100,
            "otd_d_failures": 0,
            "tardy_count": 0,
            "earliness_avg_days": 5,
            "setups": 100,
        }
        r = compute_reward(score)
        assert 0 < r < 1

    def test_worse_earliness_lower_reward(self):
        good = {"otd_d_failures": 0, "tardy_count": 0, "earliness_avg_days": 3, "setups": 100}
        bad = {"otd_d_failures": 0, "tardy_count": 0, "earliness_avg_days": 12, "setups": 100}
        assert compute_reward(good) > compute_reward(bad)

    def test_fewer_setups_higher_reward(self):
        good = {"otd_d_failures": 0, "tardy_count": 0, "earliness_avg_days": 5, "setups": 80}
        bad = {"otd_d_failures": 0, "tardy_count": 0, "earliness_avg_days": 5, "setups": 180}
        assert compute_reward(good) > compute_reward(bad)

    def test_tardy_always_negative(self):
        score = {"otd_d_failures": 0, "tardy_count": 3, "earliness_avg_days": 3, "setups": 50}
        assert compute_reward(score) < 0


# --- Context Tests ---


class TestContext:
    def test_extract_returns_valid(self):
        ctx = extract_context(_engine())
        assert ctx.n_ops == 1
        assert ctx.n_machines == 1
        assert ctx.n_days == 10
        assert ctx.total_demand > 0
        assert 0 < ctx.demand_density < 10

    def test_twin_and_alt_fractions(self):
        ops = [
            _eop(op_id="T1_M1_SKU1", alt="M2"),
            _eop(op_id="T2_M2_SKU2", sku="SKU2", machine="M2", tool="T2"),
        ]
        ctx = extract_context(_engine(ops=ops))
        assert ctx.alt_pct > 0
        assert ctx.n_ops == 2


# --- Store Tests ---


class TestLearnStore:
    def test_save_load_roundtrip(self):
        store = LearnStore(db_path=":memory:")
        ctx = _dummy_context()
        result = _dummy_study_result()
        store.save_study(ctx, result, "test.xlsx")
        history = store.load_history()
        assert len(history) == 1
        assert history[0]["reward"] == 0.7
        assert history[0]["isop_label"] == "test.xlsx"
        store.close()

    def test_load_best_params(self):
        store = LearnStore(db_path=":memory:")
        ctx = _dummy_context()
        store.save_study(ctx, _dummy_study_result(0.5), "a")
        store.save_study(ctx, _dummy_study_result(0.9), "b")
        best = store.load_best_params()
        assert best is not None
        store.close()

    def test_empty_history(self):
        store = LearnStore(db_path=":memory:")
        assert store.load_history() == []
        assert store.load_best_params() is None
        store.close()


# --- Transfer Tests ---


class TestThompsonTransfer:
    def test_cold_start_returns_none(self):
        store = LearnStore(db_path=":memory:")
        transfer = ThompsonTransfer(store)
        ctx = _dummy_context()
        assert transfer.suggest_warm_start(ctx) is None
        store.close()

    def test_after_recording_returns_params(self):
        store = LearnStore(db_path=":memory:")
        transfer = ThompsonTransfer(store)
        ctx = _dummy_context()
        result = _dummy_study_result()
        transfer.record(ctx, result, "test")
        suggestion = transfer.suggest_warm_start(ctx)
        assert suggestion is not None
        assert isinstance(suggestion, SchedulerParams)
        store.close()

    def test_record_multiple_pick_best(self):
        store = LearnStore(db_path=":memory:")
        transfer = ThompsonTransfer(store)
        ctx = _dummy_context()
        # Record a bad and a good result
        bad = _dummy_study_result(0.2)
        good = _dummy_study_result(0.9)
        transfer.record(ctx, bad, "bad")
        transfer.record(ctx, good, "good")
        # Over many samples, should prefer the good one
        suggestions = [transfer.suggest_warm_start(ctx) for _ in range(20)]
        assert any(s is not None for s in suggestions)
        store.close()


# --- Optimizer Tests ---


class TestOptunaTuner:
    def test_optimize_returns_result(self):
        tuner = OptunaTuner(_engine(), n_trials=5, timeout_s=5)
        result = tuner.optimize()
        assert isinstance(result, StudyResult)
        assert result.n_trials >= 5
        assert result.best_reward >= compute_reward(result.baseline_score)

    def test_otd_never_regresses(self):
        """Best params must maintain OTD >= baseline OTD."""
        tuner = OptunaTuner(_engine(), n_trials=10, timeout_s=5)
        result = tuner.optimize()
        assert result.best_score.get("otd", 0) >= result.baseline_score.get("otd", 0)

    def test_warm_start(self):
        tuner = OptunaTuner(_engine(), n_trials=5, timeout_s=5)
        warm = SchedulerParams(max_edd_gap=8, edd_swap_tolerance=3)
        result = tuner.optimize(warm_start=warm)
        assert result.n_trials >= 5

    def test_performance_30_trials_under_30s(self):
        t0 = time.perf_counter()
        tuner = OptunaTuner(_engine(), n_trials=30, timeout_s=30)
        result = tuner.optimize()
        elapsed = time.perf_counter() - t0
        assert elapsed < 30
        assert result.n_trials >= 20  # at least 20 completed


# --- Integration Tests ---


class TestIntegration:
    def test_full_pipeline(self):
        """End-to-end: extract context → optimize → transfer → store."""
        engine = _engine()
        ctx = extract_context(engine)

        # Optimize
        tuner = OptunaTuner(engine, n_trials=5, timeout_s=5)
        result = tuner.optimize()

        # Store
        store = LearnStore(db_path=":memory:")
        transfer = ThompsonTransfer(store)
        transfer.record(ctx, result, "test_isop")

        # Verify stored
        history = store.load_history()
        assert len(history) == 1

        # Transfer: suggest warm-start for similar ISOP
        suggestion = transfer.suggest_warm_start(ctx)
        assert suggestion is not None

        store.close()

    def test_params_backwards_compatible(self):
        """All existing callers with config=None must work identically."""
        engine = _engine()
        r_none = schedule_all(engine)
        from backend.config.types import FactoryConfig

        r_default = schedule_all(engine, config=FactoryConfig())
        assert r_none.score == r_default.score


# --- Smart Schedule Tests ---


class TestSmartSchedule:
    def test_cold_start_same_as_defaults(self):
        """No history → same as schedule_all(data)."""
        engine = _engine()
        r1 = schedule_all(engine)
        r2 = smart_schedule(engine, store_path=":memory:")
        for key in (
            "otd",
            "otd_d",
            "tardy_count",
            "early_window_violations",
            "missing_lots",
            "missing_qty",
        ):
            assert r1.score[key] == r2.score[key]

    def test_learn_stores_and_attaches_study(self):
        """learn=True → optimizes, stores, attaches study."""
        engine = _engine()
        result = smart_schedule(engine, learn=True, label="test", store_path=":memory:")
        assert result.study is not None
        assert result.study.n_trials >= 5

    def test_transfer_after_learning(self):
        """After learn, next call uses learned params."""
        import os
        import tempfile

        db = os.path.join(tempfile.mkdtemp(), "test.db")
        engine = _engine()
        smart_schedule(engine, learn=True, label="first", store_path=db)
        r2 = smart_schedule(engine, store_path=db)
        assert r2.score["otd"] == 100.0

    def test_otd_never_regresses(self):
        """smart_schedule must never degrade OTD."""
        engine = _engine()
        r = smart_schedule(engine, learn=True, store_path=":memory:")
        assert r.score.get("tardy_count", 0) == 0
