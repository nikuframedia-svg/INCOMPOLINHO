"""Training data generator for the PP1 scheduling copilot.

Extracts real factory data from the Incompol codebase and generates
JSONL training examples for QLoRA fine-tuning (Qwen2.5-14B).

Categories:
  1. Tool calling (50 examples)
  2. Reference explanations (60 examples)
  3. Capacity conflicts (60 examples)
  4. Replanning scenarios (50 examples)
  5. Twin parts (30 examples)
  6. Alerts & state (50 examples)
  7. Correct refusals (30 examples)
  8. Governance decisions (40 examples)

Usage:
  python -m apps.backend.src.domain.copilot.training_data_generator
"""

from __future__ import annotations

import json
import os
import random

# Re-export scenario generators so external imports keep working
from .training_scenarios import (  # noqa: F401
    _gen_alerts_state,
    _gen_capacity_conflicts,
    _gen_governance,
    _gen_reference_explanations,
    _gen_refusals,
    _gen_replanning,
    _gen_tool_calling,
    _gen_twin_parts,
)

# Re-export templates so external imports from this module keep working
from .training_templates import (  # noqa: F401
    CLIENTS,
    DECISION_TYPES,
    INFEASIBILITY_REASONS,
    MACHINES,
    REMEDIATION_TYPES,
    SYSTEM_PROMPT,
    _load_fixture,
    _msg,
    _tool_call_msg,
)

# ─── Main generator ──────────────────────────────────────────────────────────


def generate_all(output_dir: str = "data/training") -> tuple[int, int]:
    """Generate all training data and write JSONL files.

    Returns (train_count, eval_count).
    """
    fixture = _load_fixture()

    all_examples: list[dict] = []
    all_examples.extend(_gen_tool_calling(fixture))
    all_examples.extend(_gen_reference_explanations(fixture))
    all_examples.extend(_gen_capacity_conflicts())
    all_examples.extend(_gen_replanning())
    all_examples.extend(_gen_twin_parts())
    all_examples.extend(_gen_alerts_state(fixture))
    all_examples.extend(_gen_refusals())
    all_examples.extend(_gen_governance())

    # Shuffle
    random.seed(42)
    random.shuffle(all_examples)

    # Split 90/10
    split_idx = int(len(all_examples) * 0.9)
    train = all_examples[:split_idx]
    eval_data = all_examples[split_idx:]

    # Write
    os.makedirs(output_dir, exist_ok=True)
    train_path = os.path.join(output_dir, "dados_treino.jsonl")
    eval_path = os.path.join(output_dir, "dados_eval.jsonl")
    prompt_path = os.path.join(output_dir, "system_prompt.txt")

    with open(train_path, "w", encoding="utf-8") as f:
        for ex in train:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for ex in eval_data:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(SYSTEM_PROMPT)

    return len(train), len(eval_data)


if __name__ == "__main__":
    train_n, eval_n = generate_all()
    print(f"Generated {train_n} training + {eval_n} eval examples")
    print(f"Total: {train_n + eval_n}")
    print("Output: data/training/dados_treino.jsonl, dados_eval.jsonl, system_prompt.txt")
