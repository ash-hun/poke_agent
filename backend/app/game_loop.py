from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .agent import ClaudeAgent, extract_action_plan
from .config import get_config
from .emulator import MgbaHttpClient
from .loop_detector import LoopDetector, format_loop_warning
from .milestones import MilestoneTracker
from .observation import capture_observation, format_observation_text
from .state_store import StateStore, ToolCallRecord, TurnRecord
from .stuck_memory import StuckMemory
from .supervisor import SupervisedClient

log = logging.getLogger("game_loop")

CONTROL_TOOLS = {"mgba_tap", "mgba_tap_many", "mgba_hold", "mgba_hold_many", "mgba_release"}


class GameLoop:
    """Async game loop that runs as a background task."""

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._task: asyncio.Task | None = None
        self._paused = False
        self._stop_requested = False

    # --- Control ---

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_requested = False
        self._paused = False
        self._task = asyncio.create_task(self._run(), name="game-loop")
        self._store.set_loop_status("running")
        log.info("Game loop started")

    def stop(self) -> None:
        self._stop_requested = True
        self._paused = False
        if self._task:
            self._task.cancel()
        self._store.set_loop_status("stopped")
        log.info("Game loop stopped")

    def pause(self) -> None:
        self._paused = True
        self._store.set_loop_status("paused")
        log.info("Game loop paused")

    def resume(self) -> None:
        self._paused = False
        self._store.set_loop_status("running")
        log.info("Game loop resumed")

    @property
    def status(self) -> str:
        if self._task is None or self._task.done():
            return "stopped"
        return "paused" if self._paused else "running"

    # --- Main loop ---

    async def _run(self) -> None:
        cfg = get_config()

        emulator = MgbaHttpClient(cfg.mgba_http_base_url)
        supervisor_interventions: list[str] = []

        def on_intervention(iv) -> None:
            log.info("  [Supervisor] %s: %s", iv.reason, iv.detail)
            supervisor_interventions.append(f"{iv.reason}: {iv.detail}")

        supervised = SupervisedClient(
            client=emulator,
            directional_frames=cfg.directional_hold_frames,
            button_frames=cfg.button_tap_frames,
            settle_frames=cfg.post_action_settle_frames,
            black_frame_polls=cfg.black_frame_max_polls,
            on_intervention=on_intervention,
        )

        agent = ClaudeAgent(
            model=cfg.ai_model,
            system_prompt=cfg.system_prompt,
            max_tokens=cfg.max_tokens,
            api_key=cfg.anthropic_api_key or None,
        )

        stuck_memory = StuckMemory()
        loop_detector = LoopDetector()
        milestone_tracker = MilestoneTracker()
        recent_actions: list[str] = []
        turn = 0

        log.info("┌─────────────────────────────────────────┐")
        log.info("│       Claude Pokemon Agent  v0.2.0      │")
        log.info("└─────────────────────────────────────────┘")
        log.info("Model  : %s", cfg.ai_model)
        log.info("mGBA   : %s", cfg.mgba_http_base_url)

        try:
            while not self._stop_requested:
                # Pause handling
                while self._paused and not self._stop_requested:
                    await asyncio.sleep(0.5)

                if self._stop_requested:
                    break

                # Reload config each turn (allows live updates)
                cfg = get_config()
                agent.model = cfg.ai_model
                agent.system_prompt = cfg.system_prompt
                agent.max_tokens = cfg.max_tokens
                supervised._dir_frames = cfg.directional_hold_frames
                supervised._btn_frames = cfg.button_tap_frames
                supervised._settle_frames = cfg.post_action_settle_frames

                turn += 1
                log.info("\n═══ Turn %d ═══", turn)

                supervisor_interventions.clear()
                tool_calls_this_turn: list[ToolCallRecord] = []
                claude_text = ""
                turn_error: str | None = None
                turn_start = _now_ms()

                # Capture observation
                try:
                    obs = await capture_observation(emulator)
                except Exception as exc:
                    log.error("[Error] Observation failed: %s", exc)
                    await asyncio.sleep(2)
                    continue

                # Update memory & milestones
                stuck_memory.observe(obs, turn)
                loop_state = loop_detector.observe(obs)
                milestone = milestone_tracker.observe(obs)

                if milestone.badges_obtained > 0 or milestone.furthest:
                    badge_info = (
                        f" | Badges: {milestone.badges_obtained}/8 ({', '.join(milestone.badge_names)})"
                        if milestone.badges_obtained > 0 else ""
                    )
                    log.info("[Milestone] %s%s", milestone.furthest or "started", badge_info)

                # Hard-stuck escape
                if loop_state.is_hard_stuck:
                    log.warning(
                        "  [LoopDetector] Hard stuck — same screen for %d turns. Forcing B×3.",
                        loop_state.loop_turns,
                    )
                    try:
                        await supervised.tap("B")
                        await supervised.tap("B")
                        await supervised.tap("B")
                    except Exception as exc:
                        log.error("  [LoopDetector] Escape failed: %s", exc)
                    loop_detector.reset()
                elif loop_state.is_looping:
                    log.warning(
                        "  [LoopDetector] Loop warning — same screen for %d turns.",
                        loop_state.loop_turns,
                    )

                # Build user message
                obs_text = format_observation_text(
                    obs, recent_actions, stuck_memory.snapshot_text(), turn,
                    format_loop_warning(loop_state),
                )

                user_message = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": obs_text},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": obs.screenshot_data,
                            },
                        },
                    ],
                }

                # Execute Claude turn
                async def on_tool_call(tool_name: str, input_: dict, tool_call_id: str) -> Any:
                    nonlocal claude_text
                    log.info("  [Tool] %s %s", tool_name, input_)
                    tool_calls_this_turn.append(ToolCallRecord(name=tool_name, input=input_))

                    from .tools import execute_tool
                    result = await execute_tool(tool_name, input_, supervised)

                    stuck_memory.record_event(tool_name, input_, obs, turn)
                    _record_recent_action(tool_name, input_, recent_actions)

                    await self._store.update_in_progress(TurnRecord(
                        turn=turn,
                        timestamp=datetime.utcnow().isoformat(),
                        milestone=milestone.furthest,
                        badges=milestone.badges_obtained,
                        badge_names=milestone.badge_names,
                        screenshot=obs.screenshot_data,
                        status={
                            "frame": obs.status.frame,
                            "gameTitle": obs.status.game_title,
                            "gameCode": obs.status.game_code,
                        },
                        system_prompt=cfg.system_prompt,
                        observation_text=obs_text,
                        claude_text=claude_text,
                        action_plan=extract_action_plan(claude_text),
                        tool_calls=list(tool_calls_this_turn),
                        supervisor_interventions=list(supervisor_interventions),
                        context_messages=agent.message_count,
                        error=None,
                        duration_ms=_now_ms() - turn_start,
                    ))
                    return result

                def on_text(text: str) -> None:
                    nonlocal claude_text
                    claude_text += text
                    preview = text.strip()[:120]
                    log.info("  [Claude] %s%s", preview, "…" if len(text) > 120 else "")

                for attempt in range(3):
                    try:
                        await agent.process_turn(user_message, on_tool_call, on_text)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        turn_error = str(exc)
                        wait = 2 ** attempt
                        log.error("[Error] Turn %d attempt %d failed: %s (retry in %ds)", turn, attempt + 1, turn_error, wait)
                        if attempt < 2:
                            await asyncio.sleep(wait)
                        else:
                            log.error("[Error] Turn %d failed after 3 attempts, skipping", turn)

                log.info("  [Context] %d messages in history", agent.message_count)

                await self._store.record_turn(TurnRecord(
                    turn=turn,
                    timestamp=datetime.utcnow().isoformat(),
                    milestone=milestone.furthest,
                    badges=milestone.badges_obtained,
                    badge_names=milestone.badge_names,
                    screenshot=obs.screenshot_data,
                    status={
                        "frame": obs.status.frame,
                        "gameTitle": obs.status.game_title,
                        "gameCode": obs.status.game_code,
                    },
                    system_prompt=cfg.system_prompt,
                    observation_text=obs_text,
                    claude_text=claude_text,
                    action_plan=extract_action_plan(claude_text),
                    tool_calls=tool_calls_this_turn,
                    supervisor_interventions=list(supervisor_interventions),
                    context_messages=agent.message_count,
                    error=turn_error,
                    duration_ms=_now_ms() - turn_start,
                ))

        except asyncio.CancelledError:
            log.info("Game loop cancelled")
        except Exception as exc:
            log.error("Game loop crashed: %s", exc, exc_info=True)
        finally:
            await emulator.close()
            self._store.set_loop_status("stopped")


def _record_recent_action(tool_name: str, input_: dict, recent: list[str]) -> None:
    if tool_name not in CONTROL_TOOLS:
        return
    recent.append(f"{tool_name.replace('mgba_', '')}: {input_}")
    del recent[: max(0, len(recent) - 10)]


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)
