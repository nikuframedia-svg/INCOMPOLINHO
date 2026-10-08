"""LLM Provider — Spec 10.

Supports OpenAI and Ollama via function calling.
LLM NEVER calculates — only decides which tool to call.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod

from backend.copilot.types import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> LLMResponse:
        """Send messages + tools to LLM, return response."""


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider (GPT-4o, etc.)."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("PP1_OPENAI_API_KEY", "")
        self.model = os.environ.get("PP1_OPENAI_MODEL", "gpt-4o")
        self.client = None

    def _client(self):
        if self.api_key.strip() in {"", "dummy", "sk-proj-YOUR_KEY_HERE"}:
            raise RuntimeError("Copilot indisponível: PP1_OPENAI_API_KEY não configurada.")
        if self.client is None:
            import openai

            self.client = openai.OpenAI(api_key=self.api_key)
        return self.client

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = self._client().chat.completions.create(
            model=self.model,
            messages=full_messages,
            tools=tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in message.tool_calls
            ]

        finish = "tool_calls" if tool_calls else "stop"
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=finish,
        )


class OllamaProvider(LLMProvider):
    """Ollama local provider."""

    def __init__(self) -> None:
        import httpx

        self.base_url = os.environ.get("PP1_OLLAMA_URL", "http://localhost:11434")
        self.model = os.environ.get("PP1_OLLAMA_MODEL", "qwen2.5:14b")
        self.client = httpx.AsyncClient(timeout=60.0)

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        # Ollama function calling format
        ollama_tools = []
        for t in tools:
            fn = t.get("function", t)
            ollama_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    },
                }
            )

        payload = {
            "model": self.model,
            "messages": full_messages,
            "tools": ollama_tools,
            "stream": False,
        }

        resp = await self.client.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        message = data.get("message", {})
        content = message.get("content")

        tool_calls = None
        raw_calls = message.get("tool_calls", [])
        if raw_calls:
            tool_calls = []
            for i, tc in enumerate(raw_calls):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, dict):
                    args = json.dumps(args)
                tool_calls.append(
                    ToolCall(
                        id=f"ollama_{i}",
                        name=fn.get("name", ""),
                        arguments=args,
                    )
                )

        finish = "tool_calls" if tool_calls else "stop"
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish,
        )


def get_provider() -> LLMProvider:
    """Factory: select provider via PP1_LLM_BACKEND env var."""
    backend = os.environ.get("PP1_LLM_BACKEND", "openai").lower()
    if backend == "ollama":
        return OllamaProvider()
    return OpenAIProvider()
