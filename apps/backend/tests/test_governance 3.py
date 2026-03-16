# Tests for Governance Engine L0-L5
# Conforme Contrato C3

from src.domain.governance.engine import GovernanceEngine


class TestGovernanceEngine:
    def test_view_data_l0_always_allowed(self):
        """view_data requires L0 — always allowed."""
        result = GovernanceEngine.check_action("view_data", "L0")
        assert result.allowed is True
        assert result.required_level == "L0"
        assert result.requires_contrafactual is False
        assert result.requires_approval is False

    def test_edit_plan_frozen_l4_requires_approval(self):
        """edit_plan_frozen requires L4 — needs approval."""
        result = GovernanceEngine.check_action("edit_plan_frozen", "L4")
        assert result.allowed is True
        assert result.required_level == "L4"
        assert result.requires_approval is True
        assert result.requires_contrafactual is True

    def test_edit_plan_slushy_l3_requires_contrafactual(self):
        """edit_plan_slushy requires L3 — needs contrafactual."""
        result = GovernanceEngine.check_action("edit_plan_slushy", "L3")
        assert result.allowed is True
        assert result.required_level == "L3"
        assert result.requires_contrafactual is True
        assert result.requires_approval is False

    def test_unknown_action_denied(self):
        """Unknown actions are denied by default."""
        result = GovernanceEngine.check_action("unknown_action", "L5")
        assert result.allowed is False
        assert result.required_level == "unknown"

    def test_insufficient_level_denied(self):
        """User with lower level than required → denied."""
        result = GovernanceEngine.check_action("edit_plan_frozen", "L2")
        assert result.allowed is False
        assert result.required_level == "L4"

    def test_higher_level_allowed(self):
        """User with higher level than required → allowed."""
        result = GovernanceEngine.check_action("edit_parameters", "L5")
        assert result.allowed is True

    def test_night_shift_requires_l4(self):
        """activate_night_shift requires L4."""
        result = GovernanceEngine.check_action("activate_night_shift", "L3")
        assert result.allowed is False
        result = GovernanceEngine.check_action("activate_night_shift", "L4")
        assert result.allowed is True
        assert result.requires_approval is True

    def test_list_rules(self):
        """list_rules returns all governance rules."""
        rules = GovernanceEngine.list_rules()
        assert "view_data" in rules
        assert "edit_plan_frozen" in rules
        assert rules["edit_plan_frozen"] == "L4"

    def test_override_customer_priority_l3(self):
        """override_customer_priority requires L3."""
        result = GovernanceEngine.check_action("override_customer_priority", "L3")
        assert result.allowed is True
        assert result.requires_contrafactual is True
