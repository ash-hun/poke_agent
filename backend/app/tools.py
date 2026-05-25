from __future__ import annotations

from typing import Any

from .emulator import MGBA_BUTTONS
from .screenshot import process_screenshot, make_screenshot_path
from .supervisor import SupervisedClient

BUTTON_ENUM = list(MGBA_BUTTONS)

TOOL_DEFINITIONS = [
    {
        "name": "mgba_status",
        "description": "현재 mGBA 상태(활성 버튼, 프레임, 게임 코드/타이틀)를 반환합니다. 주입된 관측이 오래됐거나 불명확할 때만 사용하세요.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "mgba_screenshot",
        "description": "현재 mGBA 화면을 PNG로 캡처하고 반환합니다. 주입된 관측이 불충분할 때만 사용하세요.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "mgba_tap",
        "description": "버튼 하나를 짧게 눌렀다 뗍니다. A/B/Start/Select 등 비방향 입력, 대화·메뉴 조작에 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": BUTTON_ENUM, "description": "누를 GBA 버튼"},
            },
            "required": ["button"],
        },
    },
    {
        "name": "mgba_tap_many",
        "description": "여러 버튼을 동시에 짧게 눌렀다 뗍니다. 조합 입력에만 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "buttons": {
                    "type": "array",
                    "items": {"type": "string", "enum": BUTTON_ENUM},
                    "minItems": 1,
                    "maxItems": 4,
                },
            },
            "required": ["buttons"],
        },
    },
    {
        "name": "mgba_hold",
        "description": "버튼을 지정 프레임 동안 유지합니다. 이동에는 방향키 hold를 사용하세요. Supervisor가 방향키를 duration 12(1 타일)로 고정합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": BUTTON_ENUM},
                "duration": {"type": "integer", "minimum": 1, "maximum": 600, "default": 12},
            },
            "required": ["button", "duration"],
        },
    },
    {
        "name": "mgba_hold_many",
        "description": "여러 버튼을 동시에 유지합니다. 비방향 조합에만 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "buttons": {
                    "type": "array",
                    "items": {"type": "string", "enum": BUTTON_ENUM},
                    "minItems": 1,
                    "maxItems": 4,
                },
                "duration": {"type": "integer", "minimum": 1, "maximum": 600, "default": 6},
            },
            "required": ["buttons", "duration"],
        },
    },
    {
        "name": "mgba_release",
        "description": "눌린 상태로 남아있는 버튼을 해제합니다. button을 생략하면 모든 버튼을 해제합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": BUTTON_ENUM},
            },
            "required": [],
        },
    },
]


class ScreenshotResult:
    def __init__(self, data: str, path: str) -> None:
        self.data = data
        self.path = path
        self._type = "screenshot"
        self.media_type = "image/png"


async def execute_tool(tool_name: str, input_: dict[str, Any], client: SupervisedClient) -> Any:
    match tool_name:
        case "mgba_status":
            status = await client.status()
            return {
                "frame": status.frame,
                "gameTitle": status.game_title,
                "gameCode": status.game_code,
                "activeButtons": status.active_buttons,
            }

        case "mgba_screenshot":
            path = make_screenshot_path()
            await client.screenshot(path)
            data = process_screenshot(path, overlay_grid=True)
            return ScreenshotResult(data=data, path=path)

        case "mgba_tap":
            button = input_["button"]
            await client.tap(button)
            return {"ok": True, "tapped": button}

        case "mgba_tap_many":
            buttons = input_["buttons"]
            await client.tap_many(buttons)
            return {"ok": True, "tapped": buttons}

        case "mgba_hold":
            button = input_["button"]
            duration = input_.get("duration", 12)
            await client.hold(button, duration)
            return {"ok": True, "held": button, "duration": duration}

        case "mgba_hold_many":
            buttons = input_["buttons"]
            duration = input_.get("duration", 6)
            await client.hold_many(buttons, duration)
            return {"ok": True, "held": buttons, "duration": duration}

        case "mgba_release":
            button = input_.get("button")
            if button:
                await client.clear(button)
                return {"ok": True, "released": [button]}
            await client.clear_many(list(MGBA_BUTTONS))
            return {"ok": True, "released": list(MGBA_BUTTONS)}

        case _:
            raise ValueError(f"Unknown tool: {tool_name}")
