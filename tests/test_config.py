"""Tests for Spec 09 — Factory Config."""

from __future__ import annotations

import os
import tempfile


from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.config.loader import (
    load_config,
    normalize_setup_families,
    save_config,
    validate_config,
)
from backend.config.planning import normalize_subcontract_company, normalize_subcontract_rule
from backend.config.shifts import (
    clock_to_productive_offset,
    clear_legacy_common_machine_capacity_overrides,
    interval_is_productive,
    normalize_shift_updates,
    productive_offset_to_clock,
)


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
        assert c.max_run_days == 4
        assert c.max_edd_gap == 10
        assert c.lst_safety_buffer == 2
        assert c.edd_swap_tolerance == 5

    def test_day_capacity_from_shifts(self):
        c = FactoryConfig()
        assert c.day_capacity_min == 510 + 510  # A=510, B=510

    def test_3_shifts_1440(self):
        c2 = FactoryConfig(
            shifts=[
                ShiftConfig("A", 0, 480),
                ShiftConfig("B", 480, 960),
                ShiftConfig("C", 960, 1440),
            ]
        )
        assert c2.day_capacity_min == 480 + 480 + 480

    def test_1_shift_510(self):
        c = FactoryConfig(shifts=[ShiftConfig("A", 420, 930)])
        assert c.day_capacity_min == 510

    def test_cross_midnight_shift_is_explicitly_rejected(self):
        c = FactoryConfig(shifts=[ShiftConfig("N", 1320, 360)])
        assert c.day_capacity_min == 0
        assert any("anterior ao fim" in error for error in validate_config(c))

    def test_productive_coordinates_compress_a_closed_shift_gap(self):
        c = FactoryConfig(
            shifts=[ShiftConfig("A", 420, 720), ShiftConfig("B", 780, 1020)]
        )
        assert clock_to_productive_offset(c, 720) == 300
        assert clock_to_productive_offset(c, 780) == 300
        assert productive_offset_to_clock(c, 300, boundary="end") == 720
        assert productive_offset_to_clock(c, 300, boundary="start") == 780
        assert interval_is_productive(c, 720, 780) is False

    def test_public_shift_update_normalizes_midnight_end_to_day_end(self):
        shifts = normalize_shift_updates(
            [
                {"id": "A", "label": "Manhã", "start_min": 420, "end_min": 930},
                {"id": "B", "label": "Tarde", "start_min": 930, "end_min": 0},
            ]
        )

        assert shifts == [
            ShiftConfig("A", 420, 930, "Manhã"),
            ShiftConfig("B", 930, 1440, "Tarde"),
        ]
        assert sum(shift.duration_min for shift in shifts) == 1020

    def test_public_shift_update_is_canonically_sorted(self):
        shifts = normalize_shift_updates(
            [
                {"id": "B", "start_min": 930, "end_min": 1440},
                {"id": "A", "start_min": 420, "end_min": 930},
            ]
        )
        config = FactoryConfig(shifts=list(reversed(shifts)))

        assert [shift.id for shift in shifts] == ["A", "B"]
        assert config.shift_a_start == 420
        assert config.shift_a_end == 930
        assert config.shift_b_end == 1440

    def test_shift_edit_clears_legacy_common_machine_capacity_overrides(self):
        c = FactoryConfig()
        c.machines = {
            "M1": MachineConfig("M1", "Grandes", day_capacity_min=1020),
            "M2": MachineConfig("M2", "Grandes", day_capacity_min=900),
        }

        clear_legacy_common_machine_capacity_overrides(c, previous_day_capacity_min=1020)

        assert c.machines["M1"].day_capacity_min is None
        assert c.machines["M2"].day_capacity_min == 900

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
                "M20": MachineConfig("M20", "Grandes", active=False),
            }
        )
        assert "M20" not in c.machine_groups
        assert "PRM019" in c.machine_groups

    def test_machine_null_capacity_inherits_common_shifts(self):
        c = FactoryConfig(
            machines={
                "M20": MachineConfig(
                    "M20",
                    "Grandes",
                    active=True,
                    day_capacity_min=None,
                )
            }
        )
        assert validate_config(c) == []
        assert c.day_capacity_min == 1020

    def test_heterogeneous_machine_calendar_override_is_rejected(self):
        c = FactoryConfig(
            machines={
                "M20": MachineConfig(
                    "M20",
                    "Grandes",
                    active=True,
                    day_capacity_min=900,
                )
            }
        )
        errors = validate_config(c)
        assert any("calendário comum" in error for error in errors)

    def test_prm020_is_out_of_scope(self):
        c = FactoryConfig(machines={"PRM020": MachineConfig("PRM020", "Grandes")})
        assert any("fora do âmbito" in error for error in validate_config(c))


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
            assert c.day_capacity_min == 1010
            assert len(c.shifts) == 2
            assert {
                "BFP114",
                "BFP197",
                "VUL127",
                "VUL115",
            }.isdisjoint(c.twins)
            assert c.twins["BFP178"] == ["2100373X120.10", "2185094X110.10"]

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

    def test_new_sections_round_trip(self):
        """Fase 1.1: earliness window, setup overrides, calendars, per-machine OEE."""
        from backend.config.types import MachineConfig

        c = FactoryConfig(
            earliness_policy="window",
            material_release_days=4,
            early_window_enforcement="hard",
            setup_overrides=[{"sku": "SKU1", "machine": "PRM039", "hours": 1.5}],
            setup_families={"T1": [["REF-B", "REF-A"]]},
            extra_workdays=["2026-08-08"],
            machine_unavailability=[
                {
                    "id": "u1",
                    "resource": "PRM039",
                    "from": "2026-03-10",
                    "to": "2026-03-12",
                    "reason": "Manutenção",
                }
            ],
            tool_unavailability=[
                {"id": "u2", "resource": "BFP079", "from": "2026-03-16", "to": "2026-03-16", "reason": ""}
            ],
            operator_unavailability=[
                {
                    "id": "u3",
                    "group": "Grandes",
                    "shift": "A",
                    "from": "2026-04-01",
                    "to": "2026-04-03",
                    "count": 2,
                    "reason": "Férias",
                }
            ],
        )
        c.machines["PRM039"] = MachineConfig(id="PRM039", group="Grandes", oee=0.72)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_config(c, path)
            loaded = load_config(path)
        finally:
            os.unlink(path)

        assert loaded.earliness_policy == "jit"
        assert loaded.material_release_days == 5
        assert loaded.early_window_enforcement == "hard"
        assert loaded.setup_overrides == [{"sku": "SKU1", "machine": "PRM039", "hours": 1.5}]
        assert loaded.setup_families == {"T1": [["REF-A", "REF-B"]]}
        assert loaded.extra_workdays == ["2026-08-08"]
        assert loaded.machine_unavailability[0]["resource"] == "PRM039"
        assert "from" not in loaded.machine_unavailability[0]
        assert "to" not in loaded.machine_unavailability[0]
        assert loaded.machine_unavailability[0]["start_at"].startswith("2026-03-10T00:00")
        assert loaded.machine_unavailability[0]["end_at"].startswith("2026-03-13T00:00")
        assert loaded.tool_unavailability[0]["resource"] == "BFP079"
        assert loaded.operator_unavailability[0]["count"] == 2
        assert loaded.machines["PRM039"].oee == 0.72
        assert validate_config(loaded) == []

    def test_yaml_without_new_sections_loads_defaults(self):
        """Old factory.yaml files (pre-Fase 1.1) load with safe defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("factory:\n  name: Velho\nscheduler:\n  max_run_days: 5\n")
            f.flush()
            c = load_config(f.name)
        os.unlink(f.name)
        assert c.earliness_policy == "jit"
        assert c.material_release_days == 5
        assert c.early_window_enforcement == "hard"
        assert c.setup_overrides == []
        assert c.setup_families == {}
        assert c.machine_unavailability == []
        assert c.tool_unavailability == []
        assert c.operator_unavailability == []
        assert c.extra_workdays == []

    def test_failed_save_preserves_the_existing_config(self, monkeypatch, tmp_path):
        path = tmp_path / "factory.yaml"
        path.write_text("original: intact\n", encoding="utf-8")

        def fail_dump(*_args, **_kwargs):
            raise RuntimeError("disk serialization failed")

        monkeypatch.setattr("backend.config.loader.yaml.dump", fail_dump)
        try:
            save_config(FactoryConfig(), str(path))
        except RuntimeError as exc:
            assert "serialization failed" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("A failed serialization must be reported")

        assert path.read_text(encoding="utf-8") == "original: intact\n"
        assert list(tmp_path.glob(".factory.yaml.*.tmp")) == []

    def test_subcontract_calendar_read_lead_maps_to_workday_planning(self):
        company = normalize_subcontract_company(
            {"id": "SUBCONTRATO", "name": "Subcontrato", "lead_time_days": 7}
        )
        rule = normalize_subcontract_rule(
            "CF589MMA1A02.20",
            {"enabled": True, "company_id": "SUBCONTRATO", "lead_time_days": 7},
        )

        assert company["lead_time_days"] == 7
        assert company["lead_time_workdays"] == 5
        assert rule["lead_time_days"] == 7
        assert rule["lead_time_workdays"] == 5


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

    def test_scheduler_numeric_domains(self):
        c = FactoryConfig(
            max_run_days=0,
            jit_buffer_pct=1.5,
            jit_threshold=101,
            vns_max_iter=-1,
        )
        errors = validate_config(c)
        assert any("max_run_days" in error for error in errors)
        assert any("jit_buffer_pct" in error for error in errors)
        assert any("jit_threshold" in error for error in errors)
        assert any("vns_max_iter" in error for error in errors)

    def test_production_modes_and_durations(self):
        c = FactoryConfig(
            eco_lot_mode="unknown",
            min_prod_min=0,
            default_setup_hours=9,
        )
        errors = validate_config(c)
        assert any("eco_lot_mode" in error for error in errors)
        assert any("min_prod_min" in error for error in errors)
        assert any("default_setup_hours" in error for error in errors)

    def test_setup_crews_zero(self):
        c = FactoryConfig(setup_crews=0)
        errors = validate_config(c)
        assert any("crew" in e.lower() for e in errors)

    def test_setup_crews_above_one_is_not_supported_yet(self):
        c = FactoryConfig(setup_crews=2)
        errors = validate_config(c)
        assert any("exatamente 1" in e.lower() for e in errors)

    def test_invalid_earliness_policy(self):
        c = FactoryConfig(earliness_policy="asap")
        errors = validate_config(c)
        assert any("earliness_policy" in e for e in errors)

    def test_invalid_enforcement_mode(self):
        c = FactoryConfig(early_window_enforcement="strict")
        errors = validate_config(c)
        assert any("early_window_enforcement" in e for e in errors)

    def test_negative_material_release_days(self):
        c = FactoryConfig(material_release_days=-1)
        errors = validate_config(c)
        assert any("material_release_days" in e for e in errors)

    def test_setup_override_unknown_machine(self):
        from backend.config.types import MachineConfig

        c = FactoryConfig(setup_overrides=[{"sku": "S1", "machine": "PRM999", "hours": 1.0}])
        c.machines["PRM019"] = MachineConfig(id="PRM019", group="Grandes")
        errors = validate_config(c)
        assert any("PRM999" in e for e in errors)

    def test_setup_override_hours_out_of_range(self):
        c = FactoryConfig(setup_overrides=[{"sku": "S1", "machine": "PRM019", "hours": 0}])
        errors = validate_config(c)
        assert any("horas" in e for e in errors)

    def test_setup_family_normalization_is_canonical(self):
        assert normalize_setup_families(
            {" T1 ": [[" REF-B ", "REF-A", "REF-A"], ["REF-D", "REF-C"]]}
        ) == {"T1": [["REF-A", "REF-B"], ["REF-C", "REF-D"]]}

    def test_setup_families_reject_unknown_tools_singletons_and_duplicates(self):
        c = FactoryConfig(
            tools={"T1": {"primary": "M1"}},
            setup_families={
                "UNKNOWN": [["REF-X", "REF-Y"]],
                "T1": [["REF-A"], ["REF-B", "REF-C"], ["REF-C", "REF-D"]],
            },
        )

        errors = validate_config(c)

        assert any("UNKNOWN" in error and "não existe" in error for error in errors)
        assert any("pelo menos 2 SKUs" in error for error in errors)
        assert any("REF-C" in error and "mais de um grupo" in error for error in errors)

    def test_machine_oee_out_of_range(self):
        from backend.config.types import MachineConfig

        c = FactoryConfig()
        c.machines["PRM019"] = MachineConfig(id="PRM019", group="Grandes", oee=1.5)
        errors = validate_config(c)
        assert any("PRM019" in e and "OEE" in e for e in errors)

    def test_tool_setup_hours_out_of_range(self):
        c = FactoryConfig()
        c.machines["M1"] = MachineConfig(id="M1", group="Grandes")
        c.tools["T1"] = {
            "primary": "M1",
            "setup_hours": 9,
        }
        errors = validate_config(c)
        assert any("T1" in error and "setup_hours" in error for error in errors)

    def test_unavailability_bad_dates(self):
        c = FactoryConfig(
            machine_unavailability=[
                {"id": "u1", "resource": "PRM019", "from": "not-a-date", "to": "2026-03-12"}
            ]
        )
        errors = validate_config(c)
        assert any("datas inválidas" in e for e in errors)

    def test_unavailability_from_after_to(self):
        c = FactoryConfig(
            tool_unavailability=[
                {"id": "u1", "resource": "BFP079", "from": "2026-03-15", "to": "2026-03-10"}
            ]
        )
        errors = validate_config(c)
        assert any("posterior" in e for e in errors)

    def test_unavailability_ids_are_global_and_references_are_checked(self):
        c = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            tools={"T1": {"primary": "M1"}},
            machine_unavailability=[
                {
                    "id": "same",
                    "resource": "M1",
                    "start_at": "2026-03-10T07:00+00:00",
                    "end_at": "2026-03-10T08:00+00:00",
                }
            ],
            tool_unavailability=[
                {
                    "id": "same",
                    "resource": "UNKNOWN",
                    "start_at": "2026-03-10T07:00+00:00",
                    "end_at": "2026-03-10T08:00+00:00",
                }
            ],
        )
        errors = validate_config(c)
        assert any("ID repetido" in error for error in errors)
        assert any("UNKNOWN" in error for error in errors)

    def test_overlapping_operator_absences_cannot_exceed_shift_team(self):
        c = FactoryConfig(
            operators={("Grandes", "A"): 3},
            operator_unavailability=[
                {
                    "id": "o1",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-10T08:00+00:00",
                    "end_at": "2026-03-10T12:00+00:00",
                    "count": 2,
                },
                {
                    "id": "o2",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-10T10:00+00:00",
                    "end_at": "2026-03-10T14:00+00:00",
                    "count": 2,
                },
            ],
        )
        assert any("excedem equipa" in error for error in validate_config(c))

    def test_operator_overlap_outside_selected_shift_does_not_conflict(self):
        c = FactoryConfig(
            operator_unavailability=[
                {
                    "id": "o1",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-10T07:00+00:00",
                    "end_at": "2026-03-10T17:30+00:00",
                    "count": 4,
                },
                {
                    "id": "o2",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-10T17:00+00:00",
                    "end_at": "2026-03-11T08:00+00:00",
                    "count": 4,
                },
            ]
        )

        assert not any("excedem equipa" in error for error in validate_config(c))

    def test_operator_map_must_be_complete_numeric_and_nonnegative(self):
        partial = FactoryConfig(operators={("Grandes", "A"): 2})
        nonnumeric = FactoryConfig()
        nonnumeric.operators[("Grandes", "A")] = "many"  # type: ignore[assignment]
        negative = FactoryConfig()
        negative.operators[("Grandes", "A")] = -1

        assert any("Faltam operadores" in error for error in validate_config(partial))
        assert any("inteiro >= 0" in error for error in validate_config(nonnumeric))
        assert any("inteiro >= 0" in error for error in validate_config(negative))

    def test_invalid_timezone_and_holiday_are_reported_without_crashing(self):
        c = FactoryConfig(timezone="Mars/Phobos", holidays=["nao-e-data"])
        c.machine_unavailability = [
            {
                "id": "m1",
                "resource": "M1",
                "start_at": "2026-03-10T07:00",
                "end_at": "2026-03-10T08:00",
            }
        ]

        errors = validate_config(c)

        assert any("Timezone IANA inválido" in error for error in errors)
        assert any("holidays: data inválida" in error for error in errors)

    def test_operator_interval_must_touch_its_selected_shift(self):
        c = FactoryConfig(
            operator_unavailability=[
                {
                    "id": "o1",
                    "group": "Grandes",
                    "shift": "A",
                    "start_at": "2026-03-10T16:00+00:00",
                    "end_at": "2026-03-10T17:00+00:00",
                    "count": 1,
                }
            ]
        )
        assert any("não toca no turno A" in error for error in validate_config(c))

    def test_extra_workday_bad_date(self):
        c = FactoryConfig(extra_workdays=["08/08/2026"])
        errors = validate_config(c)
        assert any("extra_workdays" in e for e in errors)


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
