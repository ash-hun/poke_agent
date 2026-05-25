import Anthropic from "@anthropic-ai/sdk";
import type { ScreenshotToolResult } from "./tools/index";

export interface GameEvent {
  input?: unknown;
  output?: unknown;
  text?: string;
  toolCallId?: string;
  toolName?: string;
  type: "text" | "tool-call" | "tool-result";
}

export interface AgentCallbacks {
  onEvent?: (event: GameEvent) => void;
  onToolCall: (
    toolName: string,
    input: unknown,
    toolCallId: string
  ) => Promise<unknown>;
}

// Each game turn's start index in the messages array — used for safe context trimming.
const MIN_TURNS_TO_KEEP = 8;
const MAX_MESSAGES = MIN_TURNS_TO_KEEP * 6; // ~6 messages per game turn

export class ClaudePokemonAgent {
  readonly #client: Anthropic;
  readonly #model: string;
  readonly #systemPrompt: string;
  readonly #maxTokens: number;
  #messages: Anthropic.MessageParam[] = [];
  #turnBoundaries: number[] = []; // message index where each game turn's user message starts

  constructor(options: {
    model: string;
    systemPrompt: string;
    maxTokens?: number;
  }) {
    this.#client = new Anthropic();
    this.#model = options.model;
    this.#systemPrompt = options.systemPrompt;
    this.#maxTokens = options.maxTokens ?? 8192;
  }

  async processTurn(
    observationMessage: Anthropic.MessageParam,
    tools: Anthropic.Tool[],
    callbacks: AgentCallbacks
  ): Promise<void> {
    // Record the start of this game turn
    this.#turnBoundaries.push(this.#messages.length);
    this.#messages.push(observationMessage);

    // Tool-use loop: keep calling Claude until it stops requesting tools
    while (true) {
      const response = await this.#client.messages.create({
        model: this.#model,
        max_tokens: this.#maxTokens,
        system: this.#systemPrompt,
        tools,
        messages: this.#messages,
      });

      // Add assistant response to history
      this.#messages.push({ role: "assistant", content: response.content });

      // Emit text events
      for (const block of response.content) {
        if (block.type === "text") {
          callbacks.onEvent?.({ type: "text", text: block.text });
        }
      }

      if (response.stop_reason !== "tool_use") {
        break;
      }

      // Execute all tool calls in this response
      const toolUseBlocks = response.content.filter(
        (b): b is Anthropic.ToolUseBlock => b.type === "tool_use"
      );

      const toolResults: Anthropic.ToolResultBlockParam[] = [];

      for (const block of toolUseBlocks) {
        callbacks.onEvent?.({
          type: "tool-call",
          toolName: block.name,
          input: block.input,
          toolCallId: block.id,
        });

        let result: unknown;
        try {
          result = await callbacks.onToolCall(block.name, block.input, block.id);
        } catch (error) {
          result = {
            error: error instanceof Error ? error.message : String(error),
          };
        }

        callbacks.onEvent?.({
          type: "tool-result",
          toolName: block.name,
          output: result,
          toolCallId: block.id,
        });

        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: formatToolResultContent(block.name, result),
        });
      }

      this.#messages.push({ role: "user", content: toolResults });
    }

    this.#trimContext();
  }

  get messageCount(): number {
    return this.#messages.length;
  }

  #trimContext(): void {
    if (this.#messages.length <= MAX_MESSAGES) return;
    if (this.#turnBoundaries.length <= MIN_TURNS_TO_KEEP) return;

    const keepFromBoundaryIdx = this.#turnBoundaries.length - MIN_TURNS_TO_KEEP;
    const trimAtIndex = this.#turnBoundaries[keepFromBoundaryIdx];
    if (trimAtIndex === undefined || trimAtIndex <= 0) return;

    this.#messages = this.#messages.slice(trimAtIndex);
    this.#turnBoundaries = this.#turnBoundaries
      .slice(keepFromBoundaryIdx)
      .map((idx) => idx - trimAtIndex);
  }
}

function formatToolResultContent(
  toolName: string,
  result: unknown
): Anthropic.ToolResultBlockParam["content"] {
  // For screenshot results, include the image so Claude can see it
  if (toolName === "mgba_screenshot" && isScreenshotResult(result)) {
    return [
      { type: "text", text: `Screenshot captured at ${result.path}.` },
      {
        type: "image",
        source: {
          type: "base64",
          media_type: result.mediaType,
          data: result.data,
        },
      },
    ];
  }

  return typeof result === "string" ? result : JSON.stringify(result, null, 2);
}

function isScreenshotResult(value: unknown): value is ScreenshotToolResult {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>)["_type"] === "screenshot"
  );
}
