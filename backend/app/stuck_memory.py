from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .observation import MgbaObservation
from .pokemon_state import PokemonState

MOVEMENT_BUTTONS = frozenset({"Up", "Down", "Left", "Right"})
STUCK_THRESHOLD = 8
MAX_FAILED_EDGES = 6
MAX_RECOVERY_ATTEMPTS = 6


@dataclass
class FailedMovementEdge:
    action: str
    attempts: int
    context: str
    last_seen_turn: int


@dataclass
class RecoveryAttempt:
    action: str
    context: str
    turn: int


@dataclass
class _MovementContext:
    key: str
    label: str
    state_based: bool
    screenshot_hash: str | None = None


@dataclass
class _PendingAttempt:
    action: str
    context: _MovementContext
    turn: int


class StuckMemory:
    def __init__(self) -> None:
        self._failed_edges: dict[str, FailedMovementEdge] = {}
        self._recovery_attempts: list[RecoveryAttempt] = []
        self._last_failed_key: str | None = None
        self._pending: _PendingAttempt | None = None
        self._repeated = 0
        self._stuck_events = 0

    def observe(self, obs: MgbaObservation, turn: int) -> None:
        pending = self._pending
        self._pending = None
        if not pending:
            return

        current = _context_from_obs(obs)
        if not current or not _is_stationary(pending.context, current):
            self._last_failed_key = None
            self._repeated = 0
            return

        failed_key = f"{pending.context.key}|{pending.action}"
        if self._last_failed_key == failed_key:
            self._repeated += 1
        else:
            self._last_failed_key = failed_key
            self._repeated = 1

        if self._repeated == STUCK_THRESHOLD:
            self._stuck_events += 1

        self._record_edge(FailedMovementEdge(
            action=pending.action,
            attempts=self._repeated,
            context=pending.context.label,
            last_seen_turn=turn,
        ))

    def record_event(self, tool_name: str, input_: Any, obs: MgbaObservation, turn: int) -> None:
        action = _movement_action(tool_name, input_)
        if not action:
            self._record_recovery(tool_name, input_, obs, turn)
            return

        ctx = _context_from_obs(obs)
        if not ctx:
            self._pending = None
            return
        self._pending = _PendingAttempt(action=action, context=ctx, turn=turn)

    def snapshot_text(self) -> str:
        if not self._failed_edges:
            return ""

        edges = list(self._failed_edges.values())[-MAX_FAILED_EDGES:]
        lines = ["\nfailed movement memory:"]
        for e in edges:
            lines.append(f"- {e.context}; {e.action}; failed {e.attempts}x; last turn {e.last_seen_turn}")

        recent = self._recovery_attempts[-MAX_RECOVERY_ATTEMPTS:]
        if recent:
            lines.append("recent recovery attempts:")
            for r in recent:
                lines.append(f"- turn {r.turn}: {r.action} after {r.context}")

        return "\n".join(lines)

    def _record_edge(self, edge: FailedMovementEdge) -> None:
        key = f"{edge.context}|{edge.action}"
        self._failed_edges.pop(key, None)
        self._failed_edges[key] = edge
        while len(self._failed_edges) > MAX_FAILED_EDGES:
            oldest = next(iter(self._failed_edges))
            del self._failed_edges[oldest]

    def _record_recovery(self, tool_name: str, input_: Any, obs: MgbaObservation, turn: int) -> None:
        if not self._last_failed_key:
            return
        ctx = _context_from_obs(obs)
        if not ctx:
            return
        self._recovery_attempts.append(RecoveryAttempt(
            action=f"{tool_name.replace('mgba_', '')}: {input_}",
            context=ctx.label,
            turn=turn,
        ))
        self._recovery_attempts = self._recovery_attempts[-MAX_RECOVERY_ATTEMPTS:]


def _context_from_obs(obs: MgbaObservation) -> _MovementContext | None:
    state = obs.state
    if state and state.read_status == "available":
        if state.battle or state.map_id is None or state.position_x is None or state.position_y is None:
            return None
        direction = state.direction
        key = f"map:{state.map_id}:x:{state.position_x}:y:{state.position_y}:dir:{direction}"
        return _MovementContext(
            key=key,
            label=f"map={state.map_id} x={state.position_x} y={state.position_y} facing={direction}",
            state_based=True,
        )

    if state:
        return None

    h = hashlib.sha256(obs.screenshot_data.encode()).hexdigest()[:12]
    return _MovementContext(
        key=f"screen:{h}",
        label=f"screen={h}",
        state_based=False,
        screenshot_hash=h,
    )


def _is_stationary(before: _MovementContext, after: _MovementContext) -> bool:
    if before.state_based or after.state_based:
        return before.key == after.key
    return before.screenshot_hash == after.screenshot_hash


def _movement_action(tool_name: str, input_: Any) -> str | None:
    if tool_name not in ("mgba_hold", "mgba_tap"):
        return None
    buttons = _extract_buttons(input_)
    movement = [b for b in buttons if b in MOVEMENT_BUTTONS]
    if len(movement) != 1:
        return None
    return f"{tool_name.replace('mgba_', '')}:{movement[0]}"


def _extract_buttons(input_: Any) -> list[str]:
    if not isinstance(input_, dict):
        return []
    if isinstance(input_.get("button"), str):
        return [input_["button"]]
    if isinstance(input_.get("buttons"), list):
        return [b for b in input_["buttons"] if isinstance(b, str)]
    return []
