from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env at project root regardless of CWD
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ENV_FILE = str(_PROJECT_ROOT / ".env")

DEFAULT_SYSTEM_PROMPT = "\n\n".join([
    "You are an autonomous Pokemon Red playing agent. Your single goal is to clear the Pokemon League (defeat Champion Blue) as efficiently as possible.",
    "Control scheme:\n- mgba_tap: A/B/Start/Select, dialogues, menus, facing+interact\n- mgba_hold: directional movement (Up/Down/Left/Right)\n- Supervisor enforces: directional hold → duration 12 (1 tile), non-directional tap → duration 6\n- mgba_screenshot/mgba_status: only when injected observation is stale or ambiguous",
    "Available buttons: A, B, Select, Start, Right, Left, Up, Down, R, L.",
    "Movement guide: Red grid lines in screenshots mark 16×16 px movement cells. Solid black = blocked (walls, furniture, void). Open floor = walkable. Dark passages, stairs, thresholds, mats may be transitions — approach and test them once.",
    "Pokemon League route (optimal order):\n1. Get starter Pokemon from Prof. Oak (Pallet Town)\n2. Brock → Badge 1 (Pewter City, Rock-type)\n3. Misty → Badge 2 (Cerulean City, Water-type)\n4. Lt. Surge → Badge 3 (Vermilion City, Electric-type)\n5. Erika → Badge 4 (Celadon City, Grass-type)\n6. Koga → Badge 5 (Fuchsia City, Poison-type)\n7. Sabrina → Badge 6 (Saffron City, Psychic-type)\n8. Blaine → Badge 7 (Cinnabar Island, Fire-type)\n9. Giovanni → Badge 8 (Viridian City, Ground-type)\n10. Victory Road → Pokemon League → Elite Four → Champion Blue",
    "Each turn protocol:\n1. Read the injected observation (RAM state + screenshot)\n2. Output exactly one <action_plan>...</action_plan> block: state your current goal, assess visible blocked/open/object cells, name your target, and specify the next single action\n3. Execute exactly ONE game action via a tool call\n4. Keep any text outside action_plan under 2 lines",
    "Anti-stuck rules:\n- Never repeat a movement that shows no progress (check failed movement memory)\n- If stuck, try: face object + A, go around, check alternative paths, look for hidden passages\n- In battle: choose moves strategically based on type advantage\n- In menus/dialogue: press A or B to advance",
])


class AgentConfig(BaseSettings):
    """Runtime-configurable agent settings. Can be patched via /api/config."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    mgba_http_base_url: str = Field(
        default="http://127.0.0.1:5123", alias="MGBA_HTTP_BASE_URL"
    )
    ai_model: str = Field(default="claude-opus-4-7", alias="AI_MODEL")
    max_tokens: int = Field(default=8192, alias="MAX_TOKENS")

    # System prompt (editable at runtime)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, alias="SYSTEM_PROMPT")

    # Supervisor timing
    directional_hold_frames: int = Field(default=12, alias="DIRECTIONAL_HOLD_FRAMES")
    button_tap_frames: int = Field(default=6, alias="BUTTON_TAP_FRAMES")
    post_action_settle_frames: int = Field(default=48, alias="POST_ACTION_SETTLE_FRAMES")
    black_frame_max_polls: int = Field(default=5, alias="BLACK_FRAME_MAX_POLLS")

    # Context management
    min_turns_to_keep: int = Field(default=8, alias="MIN_TURNS_TO_KEEP")

    # Dashboard
    max_history: int = Field(default=30, alias="MAX_HISTORY")
    dashboard_port: int = Field(default=4000, alias="DASHBOARD_PORT")


# Singleton — mutated at runtime via /api/config PATCH
_config: AgentConfig | None = None


def get_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = AgentConfig()
    return _config


def patch_config(**kwargs: object) -> AgentConfig:
    """Apply partial updates to the live config."""
    cfg = get_config()
    updated = cfg.model_copy(update=kwargs)
    global _config
    _config = updated
    return _config
