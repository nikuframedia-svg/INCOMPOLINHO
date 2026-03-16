# Governance Engine — L0-L5
# Conforme CLAUDE.md:
# L0: Logging | L1: +Validação | L2: +Preview
# L3: +Contrafactual+CustoDesvio | L4: +Aprovação | L5: +Multi-aprovação

from __future__ import annotations

from .schemas import GovernanceCheck

# Mapeamento acção → nível mínimo de governance
GOVERNANCE_RULES: dict[str, str] = {
    "view_data": "L0",
    "edit_parameters": "L1",
    "edit_plan_liquid": "L2",
    "edit_plan_slushy": "L3",  # contrafactual obrigatório
    "edit_plan_frozen": "L4",  # aprovação obrigatória
    "activate_night_shift": "L4",
    "override_customer_priority": "L3",
    "delete_scenario": "L1",
}

# Descrição por nível
LEVEL_DESCRIPTIONS = {
    "L0": "Logging only",
    "L1": "Logging + Validation",
    "L2": "Logging + Validation + Preview",
    "L3": "Logging + Validation + Preview + Contrafactual + Deviation Cost",
    "L4": "Logging + Validation + Preview + Contrafactual + Deviation Cost + Approval",
    "L5": "Full governance: multi-approval required",
}


class GovernanceEngine:
    """
    Verifica se uma acção é permitida dado o nível de governance do utilizador.
    """

    @staticmethod
    def check_action(action: str, user_governance_level: str) -> GovernanceCheck:
        """
        Verificar se o utilizador pode executar a acção.

        Args:
            action: nome da acção (e.g. "edit_plan_frozen")
            user_governance_level: nível do utilizador (e.g. "L4")

        Returns:
            GovernanceCheck com allowed, required_level, requires_*, message
        """
        required_level = GOVERNANCE_RULES.get(action)

        if required_level is None:
            return GovernanceCheck(
                action=action,
                allowed=False,
                required_level="unknown",
                user_level=user_governance_level,
                requires_contrafactual=False,
                requires_approval=False,
                message=f"Unknown action: {action}. Action denied by default.",
            )

        required_num = int(required_level[1])
        user_num = int(user_governance_level[1])
        allowed = user_num >= required_num

        requires_contrafactual = required_num >= 3
        requires_approval = required_num >= 4

        if allowed:
            message = f"Action '{action}' allowed at {user_governance_level}"
            if requires_approval:
                message += " (approval required)"
            elif requires_contrafactual:
                message += " (contrafactual required)"
        else:
            message = (
                f"Action '{action}' requires {required_level} but user has {user_governance_level}"
            )

        return GovernanceCheck(
            action=action,
            allowed=allowed,
            required_level=required_level,
            user_level=user_governance_level,
            requires_contrafactual=requires_contrafactual,
            requires_approval=requires_approval,
            message=message,
        )

    @staticmethod
    def list_rules() -> dict[str, str]:
        """Retornar todas as regras de governance."""
        return dict(GOVERNANCE_RULES)

    @staticmethod
    def get_level_description(level: str) -> str:
        """Retornar descrição de um nível de governance."""
        return LEVEL_DESCRIPTIONS.get(level, "Unknown level")
