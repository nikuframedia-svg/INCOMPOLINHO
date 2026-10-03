"""NLG Templates — Spec 07 §3.

Deterministic Portuguese explanations for scheduler decisions.
Zero hallucination — pure str.format() templates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import DecisionRecord

TEMPLATES: dict[str, str] = {
    # Assign machine
    "assign_load_balance": (
        "Run {subject_id}: atribuído a {chosen} (carga {chosen_load:.0f}min) "
        "em vez de {alt} (carga {alt_load:.0f}min) — balanceamento de carga."
    ),
    "assign_edd_aware": (
        "Run {subject_id}: atribuído a {chosen} — carga urgente (prazo<={edd}) "
        "menor ({chosen_load:.0f}min vs {alt_load:.0f}min)."
    ),
    "assign_no_alt": ("Run {subject_id}: atribuído a {chosen} — sem máquina alternativa."),
    # Sequence
    "sequence_campaign": (
        "Máquina {machine_id}: {n_moves} runs reagrupados por campanha "
        "(mesma ferramenta → menos setups)."
    ),
    "sequence_interleave": (
        "Máquina {machine_id}: {n_moves} runs intercalados por urgência "
        "(deadline mais cedo → quebra campanha)."
    ),
    "sequence_2opt": ("Máquina {machine_id}: {n_moves} swaps 2-opt para reduzir setups."),
    # JIT gate
    "gate_jit": (
        "Run {subject_id}: libertação de material no dia {gate_day:.0f} "
        "(último início dia {max_gate_day:.0f}, prazo de produção dia {edd}). "
        "A produção não pode começar antes desta data."
    ),
    "gate_pullback": (
        "Run {subject_id}: JIT pullback -1 dia na {machine_id} "
        "(tardy detectado, tentativa {attempt})."
    ),
    # Split
    "split_edd_gap": (
        "Run {original_id} dividido — diferença de prazo > {max_gap}d entre lots."
    ),
    "split_infeasible": (
        "Run {original_id} dividido em early ({early_lots} lots) + late ({late_lots} lots) "
        "— produção ({total_min:.0f}min) excede capacidade até ao prazo "
        "({capacity:.0f}min)."
    ),
}


def render_decision(d: DecisionRecord) -> str:
    """Render a DecisionRecord to Portuguese explanation text."""
    template = TEMPLATES.get(d.rule)
    if not template:
        return f"{d.phase}: {d.action} → {d.chosen}"

    ctx = {**d.state_snapshot, "subject_id": d.subject_id, "chosen": d.chosen}

    # Add alt from alternatives if present
    if d.alternatives:
        ctx.setdefault("alt", d.alternatives[0].value)
        ctx.setdefault("alt_load", d.alternatives[0].score)

    try:
        return template.format(**ctx)
    except KeyError:
        return f"{d.phase}: {d.action} → {d.chosen}"
