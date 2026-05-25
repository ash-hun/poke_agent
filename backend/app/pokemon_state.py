from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from .emulator import MgbaHttpClient

BADGE_NAMES = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"]

PokemonDirection = Literal["down", "up", "left", "right", "unknown"]

_ADDRESSES = {
    "battleResult": 0xCF0B,
    "battleType": 0xD05A,
    "isInBattle": 0xD057,
    "mapId": 0xD35E,
    "playerFacing": 0xC109,
    "xCoord": 0xD362,
    "yCoord": 0xD361,
    "badges": 0xD356,
}


@dataclass
class PokemonState:
    read_status: Literal["available", "unavailable"] = "unavailable"
    battle: bool = False
    battle_result: int | None = None
    battle_type: int | None = None
    direction: PokemonDirection = "unknown"
    map_id: int | None = None
    position_x: int | None = None
    position_y: int | None = None
    badges: int = 0
    badge_count: int = 0
    dialogue_like: bool = False
    menu_like: bool = False


def _count_bits(n: int) -> int:
    count = 0
    while n:
        count += n & 1
        n >>= 1
    return count


def _format_direction(value: int) -> PokemonDirection:
    return {0: "down", 4: "up", 8: "left", 12: "right"}.get(value, "unknown")


async def read_pokemon_state(client: MgbaHttpClient) -> PokemonState:
    try:
        results = await asyncio.gather(
            client.read8(_ADDRESSES["mapId"]),
            client.read8(_ADDRESSES["yCoord"]),
            client.read8(_ADDRESSES["xCoord"]),
            client.read8(_ADDRESSES["playerFacing"]),
            client.read8(_ADDRESSES["isInBattle"]),
            client.read8(_ADDRESSES["battleType"]),
            client.read8(_ADDRESSES["battleResult"]),
            client.read8(_ADDRESSES["badges"]),
        )
        map_id, y, x, facing, in_battle, battle_type, battle_result, badges = results
        return PokemonState(
            read_status="available",
            battle=in_battle != 0,
            battle_result=battle_result,
            battle_type=battle_type,
            direction=_format_direction(facing),
            map_id=map_id,
            position_x=x,
            position_y=y,
            badges=badges,
            badge_count=_count_bits(badges),
        )
    except Exception:
        return PokemonState(read_status="unavailable")


def format_pokemon_state(state: PokemonState) -> str:
    obtained = ", ".join(n for i, n in enumerate(BADGE_NAMES) if (state.badges >> i) & 1) or "none"
    return "\n".join([
        f"readStatus: {state.read_status}",
        f"mapId: {state.map_id if state.map_id is not None else 'unknown'}",
        f"position: x={state.position_x if state.position_x is not None else 'unknown'}, y={state.position_y if state.position_y is not None else 'unknown'}",
        f"direction: {state.direction}",
        f"battle: {state.battle}",
        f"battleType: {state.battle_type if state.battle_type is not None else 'unknown'}",
        f"battleResult: {state.battle_result if state.battle_result is not None else 'unknown'}",
        f"dialogueLike: {state.dialogue_like}",
        f"menuLike: {state.menu_like}",
        f"badges: {state.badge_count}/8 ({obtained})",
    ])
