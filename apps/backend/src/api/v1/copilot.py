"""Copilot API — chat endpoint with GPT-4o function calling + widgets."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...domain.copilot.engine import execute_tool
from ...domain.copilot.prompts import build_system_prompt
from ...domain.copilot.tools import TOOLS

logger = logging.getLogger(__name__)

copilot_router = APIRouter(prefix="/copilot", tags=["copilot"])

# Map tool names → widget types for frontend rendering
TOOL_WIDGET_MAP: dict[str, str] = {
    "ver_carga_maquinas": "machine_load",
    "ver_producao_hoje": "production_table",
    "ver_alertas": "alerts_list",
    "ver_robustez": "robustness",
    "explicar_referencia": "sku_detail",
    "ver_decisoes": "decisions_table",
    "recalcular_plano": "kpi_compare",
    "sugerir_melhorias": "suggestions",
}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def _parse_tool_result(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


@copilot_router.post("/chat")
async def copilot_chat(request: ChatRequest) -> dict:
    """Chat with the copilot. Supports function calling loop + widget data."""
    api_key = os.environ.get("PP1_OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            503, "Chave OpenAI não configurada. Define PP1_OPENAI_API_KEY ou OPENAI_API_KEY."
        )

    try:
        import openai
    except ImportError:
        raise HTTPException(503, "openai package not installed.")

    model = os.environ.get("PP1_OPENAI_MODEL", "gpt-4o")
    client = openai.OpenAI(api_key=api_key)

    system_prompt = build_system_prompt()
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": m.role, "content": m.content} for m in request.messages)

    # Collect widget data from tool calls
    widgets: list[dict[str, Any]] = []

    # Function calling loop (max 5 iterations to prevent runaway)
    for _ in range(5):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message.model_dump())
            for tool_call in choice.message.tool_calls:
                result = execute_tool(
                    tool_call.function.name,
                    tool_call.function.arguments,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
                # Capture widget data if this tool produces a widget
                widget_type = TOOL_WIDGET_MAP.get(tool_call.function.name)
                if widget_type:
                    parsed = _parse_tool_result(result)
                    if parsed and "error" not in parsed:
                        widgets.append({"type": widget_type, "data": parsed})
            continue

        return {
            "response": choice.message.content or "",
            "tool_calls_made": len(messages) - len(request.messages) - 1,
            "widgets": widgets,
        }

    return {
        "response": "Atingi o limite de iterações. Tenta reformular o pedido.",
        "tool_calls_made": 5,
        "widgets": widgets,
    }


@copilot_router.get("/tools")
def list_tools() -> dict:
    """List available copilot tools."""
    return {
        "tools": [
            {"name": t["function"]["name"], "description": t["function"]["description"]}
            for t in TOOLS
        ]
    }
