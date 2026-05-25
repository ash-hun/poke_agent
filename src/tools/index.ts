import type Anthropic from "@anthropic-ai/sdk";
import { MGBA_BUTTONS, type MgbaButton } from "../mgba-http";
import { readOptimizedGameBoyScreenshotBase64 } from "../screenshot-image";
import type { SupervisedClient } from "../supervisor";
import { createScreenshotPath } from "../utils";

export interface ScreenshotToolResult {
  _type: "screenshot";
  data: string;
  mediaType: "image/png";
  path: string;
}

export function createAnthropicTools(): Anthropic.Tool[] {
  return [
    {
      name: "mgba_status",
      description:
        "현재 mGBA 상태(활성 버튼, 프레임, 게임 코드/타이틀)를 반환합니다. 주입된 관측이 오래됐거나 불명확할 때만 사용하세요.",
      input_schema: {
        type: "object" as const,
        properties: {},
        required: [],
      },
    },
    {
      name: "mgba_screenshot",
      description:
        "현재 mGBA 화면을 PNG로 캡처하고 반환합니다. 주입된 관측이 불충분할 때만 사용하세요.",
      input_schema: {
        type: "object" as const,
        properties: {},
        required: [],
      },
    },
    {
      name: "mgba_tap",
      description:
        "버튼 하나를 짧게 눌렀다 뗍니다. A/B/Start/Select 등 비방향 입력, 대화·메뉴 조작에 사용하세요. Supervisor가 타이밍을 자동 정규화합니다.",
      input_schema: {
        type: "object" as const,
        properties: {
          button: {
            type: "string",
            enum: [...MGBA_BUTTONS],
            description: "누를 GBA 버튼",
          },
        },
        required: ["button"],
      },
    },
    {
      name: "mgba_tap_many",
      description:
        "여러 버튼을 동시에 짧게 눌렀다 뗍니다. 조합 입력에만 사용하세요. 일반 이동은 mgba_hold를 사용하세요.",
      input_schema: {
        type: "object" as const,
        properties: {
          buttons: {
            type: "array",
            items: { type: "string", enum: [...MGBA_BUTTONS] },
            minItems: 1,
            maxItems: 4,
            description: "동시에 누를 버튼 목록",
          },
        },
        required: ["buttons"],
      },
    },
    {
      name: "mgba_hold",
      description:
        "버튼을 지정 프레임 동안 유지합니다. 이동에는 방향키 hold를 사용하세요. Supervisor가 방향키를 duration 12(1 타일)로 고정하고 긴 이동을 안전하게 축소합니다.",
      input_schema: {
        type: "object" as const,
        properties: {
          button: {
            type: "string",
            enum: [...MGBA_BUTTONS],
            description: "유지할 버튼",
          },
          duration: {
            type: "integer",
            minimum: 1,
            maximum: 600,
            default: 12,
            description:
              "유지할 프레임 수. Supervisor가 방향키는 12, 비방향키는 6으로 고정합니다.",
          },
        },
        required: ["button", "duration"],
      },
    },
    {
      name: "mgba_hold_many",
      description:
        "여러 버튼을 동시에 유지합니다. 비방향 조합에만 사용하세요. Supervisor는 방향키 multi-hold를 거부합니다.",
      input_schema: {
        type: "object" as const,
        properties: {
          buttons: {
            type: "array",
            items: { type: "string", enum: [...MGBA_BUTTONS] },
            minItems: 1,
            maxItems: 4,
          },
          duration: {
            type: "integer",
            minimum: 1,
            maximum: 600,
            default: 6,
          },
        },
        required: ["buttons", "duration"],
      },
    },
    {
      name: "mgba_release",
      description:
        "눌린 상태로 남아있는 버튼을 해제합니다. button을 생략하면 모든 버튼을 해제합니다.",
      input_schema: {
        type: "object" as const,
        properties: {
          button: {
            type: "string",
            enum: [...MGBA_BUTTONS],
            description: "해제할 버튼. 생략 시 모든 버튼 해제.",
          },
        },
        required: [],
      },
    },
  ];
}

export async function executeToolCall(
  toolName: string,
  input: unknown,
  client: SupervisedClient
): Promise<unknown> {
  const i = (input ?? {}) as Record<string, unknown>;

  switch (toolName) {
    case "mgba_status":
      return client.status();

    case "mgba_screenshot": {
      const path = await createScreenshotPath();
      await client.screenshot(path);
      const data = await readOptimizedGameBoyScreenshotBase64(path, {
        overlayGrid: true,
      });
      return { _type: "screenshot", data, mediaType: "image/png", path } satisfies ScreenshotToolResult;
    }

    case "mgba_tap": {
      const button = i["button"] as MgbaButton;
      await client.tap(button);
      return { ok: true, tapped: button };
    }

    case "mgba_tap_many": {
      const buttons = i["buttons"] as MgbaButton[];
      await client.tapMany(buttons);
      return { ok: true, tapped: buttons };
    }

    case "mgba_hold": {
      const button = i["button"] as MgbaButton;
      const duration = (i["duration"] as number | undefined) ?? 12;
      await client.hold(button, duration);
      return { ok: true, held: button, duration };
    }

    case "mgba_hold_many": {
      const buttons = i["buttons"] as MgbaButton[];
      const duration = (i["duration"] as number | undefined) ?? 6;
      await client.holdMany(buttons, duration);
      return { ok: true, held: buttons, duration };
    }

    case "mgba_release": {
      const button = i["button"] as MgbaButton | undefined;
      if (button) {
        await client.clear(button);
        return { ok: true, released: [button] };
      }
      await client.clearMany(MGBA_BUTTONS);
      return { ok: true, released: [...MGBA_BUTTONS] };
    }

    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}
