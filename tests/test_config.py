"""Tests for Spec 09 — Factory Config."""

from __future__ import annotations

import os
import tempfile


from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.config.loader import load_config, save_config, validate_config


# ─── FactoryConfig defaults ────────────────────────────────────────────


class TestFactoryConfig:
    def test_default_incompol_values(self):
        c = FactoryConfig()
        assert c.day_capacity_min == 1020
        assert c.shift_a_start == 420
        assert c.shift_a_end == 930
        assert c.shift_b_end == 1440
        assert c.oee_default == 0.66
        assert c.default_setup_hours == 0.5
        assert c.min_prod_min == 1.0
        assert c.max_run_days == 5
        assert c.max_edd_gap == 10
        assert c.lst_safety_buffer == 2
        assert c.edd_swap_tolerance == 5

    def test_day_capacity_from_shifts(self):
        c = FactoryConfig()
        assert c.day_capacity_min == 510 + 510  # A=510, B=510

    def test_3_shifts_1440(self):
        FactoryConfig(
            shifts=[
                ShiftConfig("A", 360, 840),  # 480
                ShiftConfig("B", 840, 1320),  # 480
                ShiftConfig("C", 1320, 1800 % 1440),  # cross-midnight: 1440-1320+0 = 120... no
            ]
        )
        # ShiftConfig C: start=1320, end=360 → cross midnight → (1440-1320)+360 = 480
        c2 = FactoryConfig(
            shifts=[
                ShiftConfig("A", 360, 840),  # 480
                ShiftConfig("B", 840, 1320),  # 480
                ShiftConfig("C", 1320, 360),  # cross midnight: 480
            ]
        )
        assert c2.day_capacity_min == 480 + 480 + 480

    def test_1_shift_510(self):
        c = FactoryConfig(shifts=[ShiftConfig("A", 420, 930)])
        assert c.day_capacity_min == 510

    def test_cross_midnight_shift(self):
        s = ShiftConfig("N", 1320, 360)  # 22:00–06:00
        assert s.duration_min == (1440 - 1320) + 360  # 480

    def test_machine_groups_property(self):
        c = FactoryConfig(
            machines={
                "PRM019": MachineConfig("PRM019", "Grandes"),
                "PRM042": MachineConfig("PRM042", "Medias"),
            }
        )
        assert c.machine_groups == {"PRM019": "Grandes", "PRM042": "Medias"}

    def test_inactive_machine_excluded(self):
        c = FactoryConfig(
            machines={
                "PRM019": MachineConfig("PRM019", "Grandes", active=True),
                "PRM020": MachineConfig("PRM020", "Grandes", active=False),
            }
        )
        assert "PRM020" not in c.machine_groups
        assert "PRM019" in c.machine_groups


# ─── Load config ───────────────────────────────────────────────────────


class TestLoadConfig:
    def test_load_missing_file_returns_defaults(self):
        c = load_config("/nonexistent/factory.yaml")
        assert c.name == "Incompol"
        assert c.day_capacity_min == 1020

    def test_load_factory_yaml(self):
        yaml_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "config",
            "factory.yaml",
        )
        if os.path.exists(yaml_path):
            c = load_config(yaml_path)
            assert c.day_capacity_min == 1020
            assert len(c.shifts) == 2

    def test_load_minimal_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("factory:\n  name: TestFactory\n")
            f.flush()
            c = load_config(f.name)
            assert c.name == "TestFactory"
            # Defaults for everything else
            assert c.day_capacity_min == 1020
        os.unlink(f.name)

    def test_scheduler_tunables_round_trip(self):
        c = FactoryConfig(
            auto_buffer=False,
            vns_enabled=False,
            vns_block_moves_enabled=True,
            compact_enabled=True,
            jit_max_retries=3,
            max_edd_span=17,
            edd_assign_threshold=4,
            productivity_earliness_ceiling_days=8.5,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_config(c, path)
            loaded = load_config(path)
        finally:
            os.unlink(path)

        assert loaded.auto_buffer is False
        assert loaded.vns_enabled is False
        assert loaded.vns_block_moves_enabled is True
        assert loaded.compact_enabled is True
        assert loaded.jit_max_retries == 3
        assert loaded.max_edd_span == 17
        assert loaded.edd_assign_threshold == 4
        assert loaded.productivity_earliness_ceiling_days == 8.5


# ─── Validation ────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_config_no_errors(self):
        errors = validate_config(FactoryConfig())
        assert errors == []

    def test_no_shifts_error(self):
        c = FactoryConfig(shifts=[])
        errors = validate_config(c)
        assert any("shift" in e.lower() or "turno" in e.lower() for e in errors)

    def test_oee_out_of_range(self):
        c = FactoryConfig(oee_default=1.5)
        errors = validate_config(c)
        assert any("oee" in e.lower() for e in errors)

    def test_setup_crews_zero(self):
        c = FactoryConfig(setup_crews=0)
        errors = validate_config(c)
        assert any("crew" in e.lower() for e in errors)

    def test_setup_crews_above_one_is_not_supported_yet(self):
        c = FactoryConfig(setup_crews=2)
        errors = validate_config(c)
        assert any("exatamente 1" in e.lower() for e in errors)


# ─── Scheduler with config ────────────────────────────────────────────


class TestSchedulerWithConfig:
    def _engine(self):
        from tests.test_learning import _engine

        return _engine()

    def test_default_config_same_as_no_config(self):
        from backend.scheduler.scheduler import schedule_all

        e = self._engine()
        r1 = schedule_all(e)
        r2 = schedule_all(e, config=FactoryConfig())
        assert r1.score == r2.score

    def test_config_backwards_compat(self):
        """All callers work without config (config=None default)."""
        from backend.scheduler.scheduler import schedule_all

        e = self._engine()
        r = schedule_all(e)
        assert r.score["otd"] == 100.0
