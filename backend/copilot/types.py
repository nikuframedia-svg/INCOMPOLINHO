"""Copilot types — Spec 10."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ToolCall:
    """LLM-requested tool invocation."""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass(slots=True)
class LLMResponse:
    """Parsed response from LLM provider."""

    content: str | None
    tool_calls: list[ToolCall] | None
    finish_reason: str  # "stop" | "tool_calls"
