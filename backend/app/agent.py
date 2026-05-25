from __future__ import annotations

import re
from typing import Any, AsyncIterator, Callable

import anthropic
import httpx

from .tools import ScreenshotResult, TOOL_DEFINITIONS

# Keep last N game turns in context
MIN_TURNS_TO_KEEP = 8
MAX_MESSAGES_PER_TURN = 6  # ~6 messages per game turn


class ClaudeAgent:
    """Multi-turn Pokemon agent (port of claude-agent.ts ClaudePokemonAgent)."""

    def __init__(
        self,
        model: str,
        system_prompt: str,
        max_tokens: int = 8192,
        api_key: str | None = None,
    ) -> None:
        _http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=120,
            ),
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
        )
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            max_retries=5,
            http_client=_http_client,
        )
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self._messages: list[dict] = []
        self._turn_boundaries: list[int] = []

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def reset(self) -> None:
        self._messages.clear()
        self._turn_boundaries.clear()

    async def process_turn(
        self,
        user_message: dict,
        on_tool_call: Callable[[str, dict, str], Any],
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """Run one game turn (may involve multiple tool-use rounds). Returns accumulated text."""
        self._turn_boundaries.append(len(self._messages))
        self._messages.append(user_message)

        full_text = ""

        while True:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                tools=TOOL_DEFINITIONS,  # type: ignore[arg-type]
                messages=self._messages,
            )

            self._messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text":
                    full_text += block.text
                    if on_text:
                        on_text(block.text)

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                try:
                    result = await on_tool_call(block.name, block.input, block.id)
                except Exception as exc:
                    result = {"error": str(exc)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _format_tool_result(block.name, result),
                })

            self._messages.append({"role": "user", "content": tool_results})

        self._trim_context()
        return full_text

    def _trim_context(self) -> None:
        max_messages = MIN_TURNS_TO_KEEP * MAX_MESSAGES_PER_TURN
        if len(self._messages) <= max_messages:
            return
        if len(self._turn_boundaries) <= MIN_TURNS_TO_KEEP:
            return

        keep_from = len(self._turn_boundaries) - MIN_TURNS_TO_KEEP
        trim_at = self._turn_boundaries[keep_from]
        if trim_at <= 0:
            return

        self._messages = self._messages[trim_at:]
        self._turn_boundaries = [
            idx - trim_at for idx in self._turn_boundaries[keep_from:]
        ]


def _format_tool_result(tool_name: str, result: Any) -> Any:
    if tool_name == "mgba_screenshot" and isinstance(result, ScreenshotResult):
        return [
            {"type": "text", "text": f"Screenshot captured at {result.path}."},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.media_type,
                    "data": result.data,
                },
            },
        ]
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        import json
        return json.dumps(result, indent=2)
    return str(result)


def extract_action_plan(text: str) -> str:
    match = re.search(r"<action_plan>([\s\S]*?)</action_plan>", text)
    return match.group(1).strip() if match else text.strip()
