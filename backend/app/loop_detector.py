from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .observation import MgbaObservation

LOOP_WARNING_THRESHOLD = 5
HARD_STUCK_THRESHOLD = 10


@dataclass
class LoopState:
    fingerprint: str
    loop_turns: int
    is_looping: bool
    is_hard_stuck: bool


class LoopDetector:
    def __init__(self) -> None:
        self._last_fp = ""
        self._loop_turns = 0

    def observe(self, obs: MgbaObservation) -> LoopState:
        fp = _fingerprint(obs)
        if fp == self._last_fp:
            self._loop_turns += 1
        else:
            self._loop_turns = 1
            self._last_fp = fp

        return LoopState(
            fingerprint=fp,
            loop_turns=self._loop_turns,
            is_looping=self._loop_turns >= LOOP_WARNING_THRESHOLD,
            is_hard_stuck=self._loop_turns >= HARD_STUCK_THRESHOLD,
        )

    def reset(self) -> None:
        self._loop_turns = 0
        self._last_fp = ""


def format_loop_warning(state: LoopState) -> str:
    if not state.is_looping:
        return ""

    lines = []
    if state.is_hard_stuck:
        lines.append(
            f"\nCRITICAL: Identical screen for {state.loop_turns} consecutive turns. "
            "System escape triggered. You MUST try a completely different action next:"
        )
    else:
        lines.append(
            f"\nSTUCK WARNING: Same screen for {state.loop_turns} turns. You must change your approach:"
        )

    lines += [
        "- Press B to cancel dialog or exit menu",
        "- If on name entry screen: navigate to END/결정 with D-pad then press A",
        "- Press Start to open the game menu",
        "- Try D-pad navigation then A to confirm a selection",
    ]
    return "\n".join(lines)


def _fingerprint(obs: MgbaObservation) -> str:
    h = hashlib.sha256(obs.screenshot_data.encode()).hexdigest()[:16]
    state = obs.state
    if (
        state
        and state.read_status == "available"
        and state.map_id is not None
        and state.position_x is not None
        and state.position_y is not None
    ):
        return f"{state.map_id}:{state.position_x}:{state.position_y}:{h}"
    return h
