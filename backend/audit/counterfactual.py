"""Counterfactual Analysis — Spec 07 §4.

Re-run the scheduler with 1 constraint changed.
"E se BFP079 estivesse na PRM039?"
"""

from __future__ import annotations

import copy
import time

from backend.cpo import optimize
from backend.types import EngineData

from .types import CounterfactualResult


def compute_counterfactual(
    question_type: str,
    params: dict,
    engine_data: EngineData,
    original_score: dict,
    config=None,
) -> CounterfactualResult:
    """Re-run scheduler with 1 constraint locked.

    Args:
        question_type: "force_machine" | "remove_jit"
        params: constraint parameters
        engine_data: original EngineData
        original_score: baseline score dict

    Returns:
        CounterfactualResult with delta and Portuguese explanation.
    """
    t0 = time.perf_counter()
    mutated = copy.deepcopy(engine_data)

    question = ""
    if question_type == "force_machine":
        tool_id = params.get("tool_id", "")
        to_machine = params["to_machine"]
        question = f"E se {tool_id} estivesse na {to_machine}?"
        for op in mutated.ops:
            if op.t == tool_id:
                op.m = to_machine
    elif question_type == "remove_jit":
        question = "E se não houvesse JIT?"

    result = optimize(mutated, mode="quick", config=config)
    cf_score = result.score

    delta = {
        "otd": cf_score.get("otd", 100) - original_score.get("otd", 100),
        "otd_d_failures": (
            cf_score.get("otd_d_failures", 0)
            - original_score.get("otd_d_failures", 0)
        ),
        "setups": cf_score.get("setups", 0) - original_score.get("setups", 0),
        "earliness": (
            cf_score.get("earliness_avg_days", 0)
            - original_score.get("earliness_avg_days", 0)
        ),
        "tardy": (
            cf_score.get("tardy_count", 0)
            - original_score.get("tardy_count", 0)
        ),
    }

    # Portuguese explanation
    if delta["otd"] < 0:
        explanation = (
            f"OTD cairia de {original_score.get('otd', 100):.1f}% "
            f"para {cf_score.get('otd', 100):.1f}%. "
            f"Tardy passaria de {original_score.get('tardy_count', 0)} "
            f"para {cf_score.get('tardy_count', 0)}."
        )
    elif delta["setups"] < 0:
        explanation = (
            f"Haveria {abs(delta['setups'])} setups a menos, "
            f"mas o OTD manteria-se em {cf_score.get('otd', 100):.1f}%."
        )
    elif delta["tardy"] > 0:
        explanation = (
            f"Tardy aumentaria de {original_score.get('tardy_count', 0)} "
            f"para {cf_score.get('tardy_count', 0)}."
        )
    else:
        explanation = "Sem impacto significativo."

    elapsed = (time.perf_counter() - t0) * 1000

    return CounterfactualResult(
        question=question,
        original_score=original_score,
        counterfactual_score=cf_score,
        delta=delta,
        explanation_pt=explanation,
        time_ms=elapsed,
    )
