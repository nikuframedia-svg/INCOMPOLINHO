"""Tests for training data generator, Poetiq cycle, and GRPO reward."""

from __future__ import annotations

import json

from src.domain.copilot.reward import compute_reward, reward_for_grpo
from src.domain.copilot.training_data_generator import (
    SYSTEM_PROMPT,
    _gen_refusals,
    _gen_tool_calling,
    _gen_twin_parts,
    _load_fixture,
    generate_all,
)


def test_generate_all_produces_files(tmp_path):
    out = str(tmp_path)
    train_n, eval_n = generate_all(output_dir=out)
    assert train_n > 200
    assert eval_n > 10
    assert (tmp_path / "dados_treino.jsonl").exists()
    assert (tmp_path / "dados_eval.jsonl").exists()
    assert (tmp_path / "system_prompt.txt").exists()


def test_jsonl_format(tmp_path):
    out = str(tmp_path)
    generate_all(output_dir=out)
    for fname in ["dados_treino.jsonl", "dados_eval.jsonl"]:
        with open(tmp_path / fname) as f:
            for line in f:
                obj = json.loads(line)
                assert "messages" in obj
                msgs = obj["messages"]
                assert msgs[0]["role"] == "system"
                assert msgs[1]["role"] == "user"
                # assistant is at position 2 (or tool_calls pattern)
                assert any(m["role"] == "assistant" for m in msgs)


def test_system_prompt_contains_real_data():
    assert "Incompol" in SYSTEM_PROMPT
    assert "PRM019" in SYSTEM_PROMPT
    assert "PRM042" in SYSTEM_PROMPT
    assert "07:00" in SYSTEM_PROMPT
    assert "OTD" in SYSTEM_PROMPT
    assert "SetupCrew" in SYSTEM_PROMPT


def test_tool_calling_examples():
    fixture = _load_fixture()
    examples = _gen_tool_calling(fixture)
    assert len(examples) >= 40
    # Check tool call format
    tool_call_examples = [e for e in examples if any(m.get("tool_calls") for m in e["messages"])]
    assert len(tool_call_examples) > 0
    for tc_ex in tool_call_examples[:5]:
        tc_msg = [m for m in tc_ex["messages"] if m.get("tool_calls")][0]
        assert tc_msg["tool_calls"][0]["type"] == "function"
        assert "name" in tc_msg["tool_calls"][0]["function"]


def test_refusal_examples():
    examples = _gen_refusals()
    assert len(examples) == 30
    # Check that refusals contain negation keywords
    for ex in examples[:5]:
        assistant_msg = [m for m in ex["messages"] if m["role"] == "assistant"][0]
        text = assistant_msg["content"].lower()
        assert any(
            kw in text for kw in ["não", "impossível", "fora", "nunca", "limitação", "obrigatório"]
        )


def test_twin_examples():
    examples = _gen_twin_parts()
    assert len(examples) >= 15
    # Should mention co-production
    has_coprod = any(
        "co-produção" in m["content"].lower() or "simultânea" in m["content"].lower()
        for ex in examples
        for m in ex["messages"]
        if m["role"] == "assistant"
    )
    assert has_coprod


# ─── Reward function tests ──────────────────────────────────────────────────


def test_reward_optimal():
    result = compute_reward(
        {
            "solver_status": "optimal",
            "kpis": {
                "otd_pct": 100,
                "total_tardiness_days": 0,
                "total_jobs": 50,
                "infeasible_count": 0,
            },
            "jobs": [
                {"machine": "PRM019", "production_minutes": 500},
                {"machine": "PRM031", "production_minutes": 480},
                {"machine": "PRM039", "production_minutes": 520},
            ],
        }
    )
    assert result.viable
    assert result.total > 0.9
    assert result.otd_score == 1.0


def test_reward_zero_on_error():
    result = compute_reward({"solver_status": "error", "kpis": {}})
    assert result.total == 0.0
    assert not result.viable


def test_reward_low_otd():
    result = compute_reward(
        {
            "solver_status": "feasible",
            "kpis": {
                "otd_pct": 80,
                "total_tardiness_days": 10,
                "total_jobs": 50,
                "infeasible_count": 5,
            },
            "jobs": [],
        }
    )
    assert result.total < 0.5
    assert not result.viable


def test_reward_for_grpo_batch():
    results = [
        {
            "solver_status": "optimal",
            "kpis": {
                "otd_pct": 100,
                "total_tardiness_days": 0,
                "total_jobs": 10,
                "infeasible_count": 0,
            },
            "jobs": [],
        },
        {"solver_status": "error", "kpis": {}},
        {
            "solver_status": "feasible",
            "kpis": {
                "otd_pct": 95,
                "total_tardiness_days": 5,
                "total_jobs": 10,
                "infeasible_count": 1,
            },
            "jobs": [],
        },
    ]
    rewards = reward_for_grpo(results)
    assert len(rewards) == 3
    assert rewards[0] > rewards[2] > rewards[1]
