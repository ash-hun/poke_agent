from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket

MAX_HISTORY = 30


@dataclass
class ToolCallRecord:
    name: str
    input: Any


@dataclass
class TurnRecord:
    turn: int
    timestamp: str
    milestone: str | None
    badges: int
    badge_names: list[str]
    screenshot: str           # base64
    status: dict              # frame, gameTitle, gameCode
    system_prompt: str
    observation_text: str
    claude_text: str
    action_plan: str
    tool_calls: list[ToolCallRecord]
    supervisor_interventions: list[str]
    context_messages: int
    error: str | None
    duration_ms: int


@dataclass
class DashboardState:
    meta: dict = field(default_factory=dict)
    current: TurnRecord | None = None
    history: list[TurnRecord] = field(default_factory=list)
    updated_at: str = ""
    loop_status: str = "stopped"   # stopped | running | paused


class StateStore:
    """Singleton shared state + WebSocket broadcaster."""

    def __init__(self) -> None:
        self._state = DashboardState()
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    def init(self, meta: dict) -> None:
        self._state.meta = meta
        self._state.updated_at = datetime.utcnow().isoformat()

    def get_state(self) -> DashboardState:
        return self._state

    def set_loop_status(self, status: str) -> None:
        self._state.loop_status = status
        self._state.updated_at = datetime.utcnow().isoformat()

    async def update_in_progress(self, record: TurnRecord) -> None:
        async with self._lock:
            if self._state.current and self._state.current.turn < record.turn:
                self._state.history.insert(0, self._state.current)
                if len(self._state.history) > MAX_HISTORY:
                    self._state.history.pop()
            self._state.current = record
            self._state.updated_at = datetime.utcnow().isoformat()
        await self._broadcast()

    async def record_turn(self, record: TurnRecord) -> None:
        async with self._lock:
            if self._state.current and self._state.current.turn < record.turn:
                self._state.history.insert(0, self._state.current)
                if len(self._state.history) > MAX_HISTORY:
                    self._state.history.pop()
            self._state.current = record
            self._state.updated_at = datetime.utcnow().isoformat()
        await self._broadcast()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        await self._send_to(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def _broadcast(self) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await self._send_to(ws)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    async def _send_to(self, ws: WebSocket) -> None:
        payload = _serialize_state(self._state)
        await ws.send_text(json.dumps(payload))


def _serialize_state(state: DashboardState) -> dict:
    return {
        "meta": state.meta,
        "loopStatus": state.loop_status,
        "updatedAt": state.updated_at,
        "current": _serialize_turn(state.current) if state.current else None,
        "history": [_serialize_turn(t) for t in state.history],
    }


def _serialize_turn(t: TurnRecord) -> dict:
    return {
        "turn": t.turn,
        "timestamp": t.timestamp,
        "milestone": t.milestone,
        "badges": t.badges,
        "badgeNames": t.badge_names,
        "screenshot": t.screenshot,
        "status": t.status,
        "systemPrompt": t.system_prompt,
        "observationText": t.observation_text,
        "claudeText": t.claude_text,
        "actionPlan": t.action_plan,
        "toolCalls": [{"name": tc.name, "input": tc.input} for tc in t.tool_calls],
        "supervisorInterventions": t.supervisor_interventions,
        "contextMessages": t.context_messages,
        "error": t.error,
        "durationMs": t.duration_ms,
    }


# Module-level singleton
store = StateStore()
