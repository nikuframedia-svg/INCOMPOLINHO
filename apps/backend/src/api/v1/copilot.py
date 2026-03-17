"""Copilot API — chat endpoint with GPT-4o function calling."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...domain.copilot.engine import execute_tool
from ...domain.copilot.prompts import build_system_prompt
from ...domain.copilot.tools import TOOLS

logger = logging.getLogger(__name__)

copilot_router = APIRouter(prefix="/copilot", tags=["copilot"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@copilot_router.post("/chat")
async def copilot_chat(request: ChatRequest) -> dict:
    """Chat with the copilot. Supports function calling loop."""
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
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": m.role, "content": m.content} for m in request.messages)

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
            continue

        return {
            "response": choice.message.content or "",
            "tool_calls_made": len(messages) - len(request.messages) - 1,
        }

    return {
        "response": "Atingi o limite de iterações. Tenta reformular o pedido.",
        "tool_calls_made": 5,
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
