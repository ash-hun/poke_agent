from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .emulator import MgbaHttpClient, MgbaStatus
from .pokemon_state import PokemonState, read_pokemon_state, format_pokemon_state
from .screenshot import process_screenshot, make_screenshot_path


@dataclass
class MgbaObservation:
    screenshot_data: str          # base64 PNG
    screenshot_path: str
    status: MgbaStatus
    state: PokemonState | None = None


async def capture_observation(client: MgbaHttpClient) -> MgbaObservation:
    path = make_screenshot_path()
    status, state, _ = await asyncio.gather(
        client.status(),
        read_pokemon_state(client),
        client.screenshot(path),
    )
    data = process_screenshot(path, overlay_grid=True)
    return MgbaObservation(
        screenshot_data=data,
        screenshot_path=path,
        status=status,
        state=state,
    )


def format_observation_text(
    obs: MgbaObservation,
    recent_actions: list[str],
    stuck_memory_text: str,
    turn: int,
    loop_warning: str = "",
) -> str:
    parts = [
        f"Turn {turn}. Observe the current game state and decide on the best action to progress toward clearing the Pokemon League.",
        f"\nCurrent mGBA status:\n{_format_status(obs.status)}",
    ]

    if obs.state and obs.state.read_status == "available":
        parts.append(f"\n\nCurrent compact Pokémon state:\n{format_pokemon_state(obs.state)}")

    if recent_actions:
        actions_text = "\n".join(f"- {a}" for a in recent_actions)
        parts.append(f"\nrecent actions to avoid repeating blindly:\n{actions_text}")

    if loop_warning:
        parts.append(loop_warning)

    if stuck_memory_text:
        parts.append(stuck_memory_text)

    parts.append(
        "\nCurrent screenshot: attached image below. Red grid lines are movement guide lines marking 16x16 Game Boy movement-cell boundaries. "
        "Distinguish blocked cells (walls, furniture, solid black) from walkable floor tiles. "
        "Dark passages, stairs, mats, and thresholds may be map transitions — approach and test them. "
        "Explore open unseen space or face objects and press A to interact."
    )

    return "".join(parts)


def _format_status(status: MgbaStatus) -> str:
    active = ", ".join(status.active_buttons) or "none"
    game = " ".join(filter(None, [status.game_title, status.game_code])) or "unknown"
    return "\n".join([
        f"frame: {status.frame if status.frame is not None else 'unknown'}",
        f"game: {game}",
        f"active buttons: {active}",
    ])
