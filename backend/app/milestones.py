from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .observation import MgbaObservation
from .pokemon_state import PokemonState, BADGE_NAMES

MILESTONES = [
    "new-game-started",
    "player-control-reached",
    "first-battle-completed",
    "first-pokemon-obtained",
    "badge-1-boulder",
    "badge-2-cascade",
    "badge-3-thunder",
    "badge-4-rainbow",
    "badge-5-soul",
    "badge-6-marsh",
    "badge-7-volcano",
    "badge-8-earth",
    "all-badges-obtained",
    "victory-road-entered",
    "elite-four-started",
    "league-cleared",
]

_MILESTONE_RANK = {m: i for i, m in enumerate(MILESTONES)}

BADGE_MILESTONES = [
    "badge-1-boulder", "badge-2-cascade", "badge-3-thunder", "badge-4-rainbow",
    "badge-5-soul", "badge-6-marsh", "badge-7-volcano", "badge-8-earth",
]


@dataclass
class MilestoneSnapshot:
    furthest: str | None
    badges_obtained: int
    badge_names: list[str]


class MilestoneTracker:
    def __init__(self) -> None:
        self._furthest: str | None = None
        self._prev_state: PokemonState | None = None
        self._prev_badges = 0

    def observe(self, obs: MgbaObservation) -> MilestoneSnapshot:
        state = obs.state
        if state and state.read_status == "available":
            self._check_badge_milestones(state)
            self._check_game_milestones(state)
            self._prev_state = state
            self._prev_badges = state.badges
        return self.snapshot()

    def snapshot(self) -> MilestoneSnapshot:
        badges = self._prev_state.badges if self._prev_state else self._prev_badges
        badge_names = [n for i, n in enumerate(BADGE_NAMES) if (badges >> i) & 1]
        return MilestoneSnapshot(
            furthest=self._furthest,
            badges_obtained=len(badge_names),
            badge_names=badge_names,
        )

    def _check_badge_milestones(self, state: PokemonState) -> None:
        if state.badge_count == 0:
            return
        for i in range(8):
            if (state.badges >> i) & 1 and not ((self._prev_badges >> i) & 1):
                if i < len(BADGE_MILESTONES):
                    self._advance(BADGE_MILESTONES[i])
        if state.badge_count == 8:
            self._advance("all-badges-obtained")

    def _check_game_milestones(self, state: PokemonState) -> None:
        if state.map_id is None:
            return
        if self._prev_state and self._prev_state.battle and not state.battle:
            self._advance("first-battle-completed")
        if _is_player_control(state):
            self._advance("player-control-reached")
        elif state.menu_like:
            self._advance("new-game-started")

    def _advance(self, milestone: str) -> None:
        if _milestone_rank(milestone) > _milestone_rank(self._furthest):
            self._furthest = milestone


def _is_player_control(state: PokemonState) -> bool:
    return (
        not state.battle
        and not state.dialogue_like
        and not state.menu_like
        and state.direction != "unknown"
    )


def _milestone_rank(m: str | None) -> int:
    if m is None:
        return -1
    return _MILESTONE_RANK.get(m, -1)
