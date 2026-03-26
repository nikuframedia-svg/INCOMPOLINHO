"""Copilot FastAPI endpoint — Spec 10.

POST /api/copilot/chat  — LLM chat with function calling
POST /api/copilot/load  — Load ISOP and initialize state
"""

from __future__ import annotations

import json
import logging

from dotenv import load_dotenv

load_dotenv()

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config.loader import load_config
from backend.copilot.engine import WIDGET_TOOLS, execute_tool
from backend.copilot.llm_provider import get_provider
from backend.copilot.prompts import build_system_prompt
from backend.copilot.state import state
from backend.copilot.tools import TOOLS
from backend.learning.smart import smart_schedule
from backend.parser.isop_reader import read_isop
from backend.transform.transform import transform

logger = logging.getLogger(__name__)

from backend.api.console import router as console_router
from backend.api.data import router as data_router

app = FastAPI(title="PP1 Copilot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(console_router)
app.include_router(data_router)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class LoadRequest(BaseModel):
    isop_path: str
    config_path: str = "config/factory.yaml"
    master_path: str = "config/incompol.yaml"


@app.post("/api/copilot/chat")
async def copilot_chat(request: ChatRequest):
    """Chat with the copilot. LLM decides which tools to call."""
    provider = get_provider()
    system_prompt = build_system_prompt(state)
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    widgets = []
    tools_used = 0

    for iteration in range(5):  # max 5 tool-call rounds
        response = await provider.chat_with_tools(messages, TOOLS, system_prompt)

        if response.tool_calls:
            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                result_json, is_widget = execute_tool(tc.name, tc.arguments)
                tools_used += 1

                if is_widget:
                    try:
                        parsed = json.loads(result_json)
                        if "error" not in parsed:
                            widgets.append({"type": "dynamic_viz", "data": parsed})
                    except json.JSONDecodeError:
                        pass

                # Append tool result for next LLM turn
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                })

            continue

        # No tool calls — final response
        return {
            "response": response.content or "",
            "widgets": widgets,
            "tools_used": tools_used,
        }

    return {
        "response": "Limite de iterações atingido.",
        "widgets": widgets,
        "tools_used": tools_used,
    }


@app.post("/api/copilot/load")
async def load_isop(request: LoadRequest):
    """Load an ISOP file and initialize the copilot state."""
    config = load_config(request.config_path)

    with open(request.master_path) as f:
        master = yaml.safe_load(f)

    rows, workdays, has_twin = read_isop(request.isop_path)
    engine_data = transform(rows, workdays, has_twin, master)
    result = smart_schedule(
        engine_data,
        learn=True,
        label=request.isop_path,
        audit=True,
        config=config,
    )

    state.engine_data = engine_data
    state.config = config
    state.update_schedule(result)
    state._load_rules()

    # DQA trust index
    from backend.dqa import compute_trust_index

    trust = compute_trust_index(engine_data, config)
    state.trust_index = trust

    # Journal summary
    journal_summary = None
    if result.journal:
        journal_summary = {
            "total": len(result.journal),
            "warnings": len([e for e in result.journal if e.get("severity") in ("warn", "error")]),
        }

    learning_info = None
    if result.study:
        learning_info = {
            "optimized": True,
            "n_trials": result.study.n_trials,
            "confidence": result.study.confidence,
            "improvement": result.study.improvement,
        }

    return {
        "status": "ok",
        "n_ops": len(engine_data.ops),
        "n_segments": len(result.segments),
        "score": result.score,
        "time_ms": result.time_ms,
        "trust_index": {"score": trust.score, "gate": trust.gate},
        "journal_summary": journal_summary,
        "learning": learning_info,
    }


@app.get("/api/copilot/health")
async def health():
    """Health check."""
    has_data = state.engine_data is not None
    return {
        "status": "ok",
        "has_data": has_data,
        "n_segments": len(state.segments),
    }
