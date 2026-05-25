from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Final

import httpx

MGBA_BUTTONS: Final[tuple[str, ...]] = (
    "A", "B", "Select", "Start", "Right", "Left", "Up", "Down", "R", "L"
)
BUTTON_SET: Final[frozenset[str]] = frozenset(MGBA_BUTTONS)

_RETRY_ATTEMPTS = 2
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
_RETRYABLE_ERROR_CODES = {
    "ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EAI_AGAIN",
}


@dataclass
class MgbaStatus:
    active_buttons: list[str] = field(default_factory=list)
    frame: int | None = None
    game_code: str = ""
    game_title: str = ""


class MgbaHttpError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Emulator request failed: {status_code} - {body}")
        self.status_code = status_code
        self.body = body


class MgbaHttpClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def _request(
        self,
        path: str,
        method: str = "GET",
        params: dict | None = None,
    ) -> str:
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                if method == "POST":
                    resp = await self._client.post(url, params=params or {})
                else:
                    resp = await self._client.get(url, params=params or {})

                if not resp.is_success:
                    err = MgbaHttpError(resp.status_code, resp.text)
                    if attempt < _RETRY_ATTEMPTS and resp.status_code in _RETRYABLE_STATUSES:
                        last_exc = err
                        continue
                    raise err

                return resp.text.strip()

            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt >= _RETRY_ATTEMPTS:
                    raise
                await asyncio.sleep(0.1)

        raise last_exc or RuntimeError("mGBA retry exhausted")

    async def tap(self, button: str) -> str:
        return await self._request("/mgba-http/button/tap", "POST", {"button": button})

    async def tap_many(self, buttons: list[str]) -> str:
        return await self._request("/mgba-http/button/tapmany", "POST", {"buttons": buttons})

    async def hold(self, button: str, duration: int) -> str:
        return await self._request("/mgba-http/button/hold", "POST", {"button": button, "duration": duration})

    async def hold_many(self, buttons: list[str], duration: int) -> str:
        return await self._request("/mgba-http/button/holdmany", "POST", {"buttons": buttons, "duration": duration})

    async def clear(self, button: str) -> str:
        return await self._request("/mgba-http/button/clear", "POST", {"button": button})

    async def clear_many(self, buttons: list[str]) -> str:
        return await self._request("/mgba-http/button/clearmany", "POST", {"buttons": buttons})

    async def get_all_buttons(self) -> list[str]:
        body = await self._request("/mgba-http/button/getall")
        return [b.strip() for b in body.split(",") if b.strip() in BUTTON_SET]

    async def screenshot(self, path: str) -> str:
        return await self._request("/core/screenshot", "POST", {"path": path})

    async def read8(self, address: int) -> int:
        body = await self._request("/core/read8", params={"address": f"0x{address:X}"})
        value = int(body)
        if not (0 <= value <= 255):
            raise ValueError(f"Invalid read8 response for address {address:#x}: {body}")
        return value

    async def status(self) -> MgbaStatus:
        active_buttons, frame_text, game_code, game_title = await asyncio.gather(
            self.get_all_buttons(),
            self._request("/core/currentframe"),
            self._request("/core/getgamecode"),
            self._request("/core/getgametitle"),
        )
        try:
            frame: int | None = int(frame_text)
        except (ValueError, TypeError):
            frame = None

        return MgbaStatus(
            active_buttons=active_buttons,
            frame=frame,
            game_code=game_code,
            game_title=game_title,
        )

    async def close(self) -> None:
        await self._client.aclose()
