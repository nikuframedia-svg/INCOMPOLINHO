"""PRM020 is outside the factory model without dropping production."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.config.planning import apply_effective_planning_config, enforce_machine_scope
from backend.config.types import FactoryConfig, MachineConfig
from backend.types import EngineData, MachineInfo


def _data() -> EngineData:
    return EngineData(
        ops=[],
        machines=[
            MachineInfo("PRM019", "Grandes", 1020),
            MachineInfo("PRM020", "Grandes", 1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=["2026-09-24"],
        n_days=1,
        machine_blocked_days={"PRM020": {0}},
        machine_blocked_intervals={"PRM020": [{"start_day": 0}]},
    )


def _config() -> FactoryConfig:
    return FactoryConfig(
        machines={
            "PRM019": MachineConfig("PRM019", "Grandes"),
            "PRM020": MachineConfig("PRM020", "Grandes"),
        },
        tools={"T1": {"primary": "PRM019", "alt": "PRM020"}},
        machine_unavailability=[{"resource": "PRM020", "start": "2026-09-24"}],
        setup_overrides=[{"machine": "PRM020", "hours": 1}],
    )


def test_legacy_empty_machine_is_removed_from_all_effective_resources():
    config, data = _config(), _data()

    enforce_machine_scope(config, data)

    assert list(config.machines) == ["PRM019"]
    assert config.tools["T1"] == {"primary": "PRM019"}
    assert config.machine_unavailability == []
    assert config.setup_overrides == []
    assert [machine.id for machine in data.machines] == ["PRM019"]
    assert "PRM020" not in data.machine_blocked_days
    assert "PRM020" not in data.machine_blocked_intervals
    assert not data.ops


def test_effective_planning_cannot_reintroduce_legacy_machine():
    config, data = _config(), _data()
    apply_effective_planning_config(data, config)
    assert "PRM020" not in {machine.id for machine in data.machines}
    assert "PRM020" not in config.machines


@pytest.mark.parametrize("machine_field", ["m", "alt"])
def test_scope_rejects_real_demand_instead_of_discarding_it(machine_field):
    config, data = _config(), _data()
    operation = SimpleNamespace(sku="SKU-1", m="PRM019", alt=None)
    setattr(operation, machine_field, "PRM020")
    data.ops.append(operation)
    before = deepcopy(data)

    with pytest.raises(ValueError, match="PRM020 fora do âmbito"):
        enforce_machine_scope(config, data)

    assert data == before


def test_scope_rejects_saved_production_on_excluded_machine():
    config, data = _config(), _data()
    segment = SimpleNamespace(machine_id="PRM020")
    with pytest.raises(ValueError, match="plano contém produção"):
        enforce_machine_scope(config, data, [segment])
