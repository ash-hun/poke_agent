from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from .emulator import MgbaHttpClient, MGBA_BUTTONS, BUTTON_SET
from .screenshot import is_black_frame, make_screenshot_path

DIRECTION_BUTTONS = frozenset({"Up", "Down", "Left", "Right"})


@dataclass
class SupervisorIntervention:
    reason: str
    detail: str


class SupervisedClient:
    """Wraps MgbaHttpClient with timing normalization logic (port of supervisor.ts)."""

    def __init__(
        self,
        client: MgbaHttpClient,
        directional_frames: int = 12,
        button_frames: int = 6,
        settle_frames: int = 48,
        black_frame_polls: int = 5,
        on_intervention: Callable[[SupervisorIntervention], None] | None = None,
    ) -> None:
        self._client = client
        self._dir_frames = directional_frames
        self._btn_frames = button_frames
        self._settle_frames = settle_frames
        self._black_polls = black_frame_polls
        self._on_intervention = on_intervention

    # --- Public API (mirrors MgbaHttpClient) ---

    async def status(self):
        return await self._client.status()

    async def screenshot(self, path: str) -> str:
        return await self._client.screenshot(path)

    async def clear(self, button: str) -> str:
        self._require_button(button)
        return await self._client.clear(button)

    async def clear_many(self, buttons: list[str]) -> str:
        for b in buttons:
            self._require_button(b)
        return await self._client.clear_many(buttons)

    async def tap(self, button: str) -> str:
        button = self._require_button(button)
        start_frame = await self._current_frame()
        duration = self._dir_frames if _is_direction(button) else self._btn_frames
        result = await self._client.hold(button, duration)
        self._intervene(
            reason="timing-normalized",
            detail=f"normalized tap {button} to hold duration {duration}",
        )
        await self._settle(start_frame)
        return result

    async def tap_many(self, buttons: list[str]) -> str:
        buttons = [self._require_button(b) for b in buttons]
        start_frame = await self._current_frame()
        result = await self._client.hold_many(buttons, self._btn_frames)
        self._intervene(
            reason="timing-normalized",
            detail=f"normalized multi-tap {'+'.join(buttons)} to hold duration {self._btn_frames}",
        )
        await self._settle(start_frame)
        return result

    async def hold(self, button: str, duration: int) -> str:
        button = self._require_button(button)
        start_frame = await self._current_frame()
        fixed = self._dir_frames if _is_direction(button) else self._btn_frames
        if duration != fixed:
            self._intervene(
                reason="long-movement-split" if _is_direction(button) and duration > fixed else "timing-normalized",
                detail=f"normalized hold {button} duration {duration} to {fixed}",
            )
        result = await self._client.hold(button, fixed)
        await self._settle(start_frame)
        return result

    async def hold_many(self, buttons: list[str], duration: int) -> str:
        buttons = [self._require_button(b) for b in buttons]
        if any(_is_direction(b) for b in buttons):
            self._intervene(
                reason="invalid-button",
                detail=f"rejected directional multi-hold {'+'.join(buttons)}",
            )
            raise ValueError("Supervisor rejected directional multi-button movement")
        start_frame = await self._current_frame()
        if duration != self._btn_frames:
            self._intervene(
                reason="timing-normalized",
                detail=f"normalized multi-hold {'+'.join(buttons)} duration {duration} to {self._btn_frames}",
            )
        result = await self._client.hold_many(buttons, self._btn_frames)
        await self._settle(start_frame)
        return result

    # --- Internals ---

    def _require_button(self, button: str) -> str:
        if button not in BUTTON_SET:
            self._intervene(reason="invalid-button", detail=f"rejected invalid button {button}")
            raise ValueError(f"Supervisor rejected invalid button: {button}")
        return button

    def _intervene(self, reason: str, detail: str) -> None:
        if self._on_intervention:
            self._on_intervention(SupervisorIntervention(reason=reason, detail=detail))

    async def _current_frame(self) -> int | None:
        try:
            status = await self._client.status()
            return status.frame
        except Exception:
            return None

    async def _settle(self, start_frame: int | None) -> None:
        if start_frame is None:
            return
        target = start_frame + self._settle_frames
        polls = 0
        while True:
            polls += 1
            status = await self._client.status()
            if status.frame is not None and status.frame >= target:
                if polls > 1:
                    self._intervene(
                        reason="settle-wait",
                        detail=f"settled from frame {start_frame} to {status.frame} after {polls} polls",
                    )
                return

    async def wait_through_black_frames(self) -> dict:
        black_frames = 0
        for poll in range(1, self._black_polls + 1):
            path = make_screenshot_path()
            await self._client.screenshot(path)
            if not is_black_frame(path):
                return {"black_frames": black_frames, "polls": poll}
            black_frames += 1
            self._intervene(
                reason="black-frame-wait",
                detail=f"black/loading frame {poll}",
            )
        return {"black_frames": black_frames, "polls": self._black_polls}


def _is_direction(button: str) -> bool:
    return button in DIRECTION_BUTTONS
