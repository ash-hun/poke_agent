import type Anthropic from "@anthropic-ai/sdk";
import { ClaudePokemonAgent } from "./claude-agent";
import { initDashboard, recordTurn, updateInProgress, extractActionPlan } from "./dashboard";
import type { ToolCallRecord } from "./dashboard";
import { env } from "./env";
import { MgbaHttpClient } from "./mgba-http";
import { PokemonLeagueMilestoneTracker } from "./milestones";
import { captureMgbaObservation, formatObservationText } from "./observation";
import { createSupervisedMgbaClient } from "./supervisor";
import { StuckMemory } from "./stuck-memory";
import { LoopDetector, formatLoopWarning } from "./loop-detector";
import { createAnthropicTools, executeToolCall } from "./tools/index";
import { sleep } from "./utils";

const SYSTEM_PROMPT = [
  "You are an autonomous Pokemon Red playing agent. Your single goal is to clear the Pokemon League (defeat Champion Blue) as efficiently as possible.",

  "Control scheme:\n- mgba_tap: A/B/Start/Select, dialogues, menus, facing+interact\n- mgba_hold: directional movement (Up/Down/Left/Right)\n- Supervisor enforces: directional hold → duration 12 (1 tile), non-directional tap → duration 6\n- mgba_screenshot/mgba_status: only when injected observation is stale or ambiguous",

  "Available buttons: A, B, Select, Start, Right, Left, Up, Down, R, L.",

  "Movement guide: Red grid lines in screenshots mark 16×16 px movement cells. Solid black = blocked (walls, furniture, void). Open floor = walkable. Dark passages, stairs, thresholds, mats may be transitions — approach and test them once.",

  "Pokemon League route (optimal order):\n1. Get starter Pokemon from Prof. Oak (Pallet Town)\n2. Brock → Badge 1 (Pewter City, Rock-type)\n3. Misty → Badge 2 (Cerulean City, Water-type)\n4. Lt. Surge → Badge 3 (Vermilion City, Electric-type)\n5. Erika → Badge 4 (Celadon City, Grass-type)\n6. Koga → Badge 5 (Fuchsia City, Poison-type)\n7. Sabrina → Badge 6 (Saffron City, Psychic-type)\n8. Blaine → Badge 7 (Cinnabar Island, Fire-type)\n9. Giovanni → Badge 8 (Viridian City, Ground-type)\n10. Victory Road → Pokemon League → Elite Four → Champion Blue",

  "Each turn protocol:\n1. Read the injected observation (RAM state + screenshot)\n2. Output exactly one <action_plan>...</action_plan> block: state your current goal, assess visible blocked/open/object cells, name your target, and specify the next single action\n3. Execute exactly ONE game action via a tool call\n4. Keep any text outside action_plan under 2 lines",

  "Anti-stuck rules:\n- Never repeat a movement that shows no progress (check failed movement memory)\n- If stuck, try: face object + A, go around, check alternative paths, look for hidden passages\n- In battle: choose moves strategically based on type advantage\n- In menus/dialogue: press A or B to advance",
].join("\n\n");

const mgbaClient = new MgbaHttpClient({ baseUrl: env.MGBA_HTTP_BASE_URL });

const supervisorInterventions: string[] = [];
const supervisedClient = createSupervisedMgbaClient(mgbaClient, {
  onIntervention: (intervention) => {
    console.log(`  [Supervisor] ${intervention.reason}: ${intervention.detail}`);
    supervisorInterventions.push(`${intervention.reason}: ${intervention.detail}`);
  },
});

const agent = new ClaudePokemonAgent({
  model: env.AI_MODEL,
  systemPrompt: SYSTEM_PROMPT,
  maxTokens: 8192,
});

const stuckMemory = new StuckMemory();
const loopDetector = new LoopDetector();
const milestoneTracker = new PokemonLeagueMilestoneTracker();
const recentActions: string[] = [];
const tools = createAnthropicTools();
let turn = 0;

console.log("┌─────────────────────────────────────────┐");
console.log("│       Claude Pokemon Agent  v0.1.0      │");
console.log("└─────────────────────────────────────────┘");
console.log(`Model  : ${env.AI_MODEL}`);
console.log(`mGBA   : ${env.MGBA_HTTP_BASE_URL}`);
console.log("Goal   : Clear Pokemon League");
console.log("Stop   : Ctrl-C\n");

await initDashboard({
  model: env.AI_MODEL,
  mgbaUrl: env.MGBA_HTTP_BASE_URL,
  startedAt: new Date().toISOString(),
});

while (true) {
  turn += 1;
  console.log(`\n═══ Turn ${turn} ═══`);

  supervisorInterventions.length = 0;
  const toolCallsThisTurn: ToolCallRecord[] = [];
  let claudeText = "";
  let turnError: string | null = null;
  const turnStart = Date.now();

  // Capture observation
  let observation;
  try {
    observation = await captureMgbaObservation(mgbaClient);
  } catch (error) {
    console.error(
      `[Error] Observation failed: ${error instanceof Error ? error.message : String(error)}`
    );
    console.log("Retrying in 2s...");
    await sleep(2000);
    continue;
  }

  // Update memory and milestones
  stuckMemory.observe(observation, turn);
  const loopState = loopDetector.observe(observation);
  const milestone = milestoneTracker.observe(observation);
  if (milestone.badgesObtained > 0 || milestone.furthest) {
    const badgeInfo =
      milestone.badgesObtained > 0
        ? ` | Badges: ${milestone.badgesObtained}/8 (${milestone.badgeNames.join(", ")})`
        : "";
    console.log(
      `[Milestone] ${milestone.furthest ?? "started"}${badgeInfo}`
    );
  }

  // System escape: directly press B×3 when hard stuck, then reset detector
  if (loopState.isHardStuck) {
    console.log(
      `  [LoopDetector] Hard stuck — same screen for ${loopState.loopTurns} turns. Forcing B×3 escape.`
    );
    try {
      await supervisedClient.tap("B");
      await supervisedClient.tap("B");
      await supervisedClient.tap("B");
    } catch (escapeError) {
      console.error(
        `  [LoopDetector] Escape failed: ${escapeError instanceof Error ? escapeError.message : String(escapeError)}`
      );
    }
    loopDetector.reset();
  } else if (loopState.isLooping) {
    console.log(
      `  [LoopDetector] Loop warning — same screen for ${loopState.loopTurns} turns.`
    );
  }

  // Build Anthropic user message with observation
  const observationText = formatObservationText(
    observation,
    recentActions,
    stuckMemory.snapshot(),
    turn,
    formatLoopWarning(loopState)
  );

  const userMessage: Anthropic.MessageParam = {
    role: "user",
    content: [
      { type: "text", text: observationText },
      {
        type: "image",
        source: {
          type: "base64",
          media_type: "image/png",
          data: observation.screenshot.data,
        },
      },
    ],
  };

  // Execute Claude turn (may involve multiple tool-use cycles)
  try {
    await agent.processTurn(userMessage, tools, {
      onToolCall: async (toolName, input, _toolCallId) => {
        console.log(`  [Tool] ${toolName} ${JSON.stringify(input)}`);
        toolCallsThisTurn.push({ name: toolName, input });
        const result = await executeToolCall(toolName, input, supervisedClient);

        stuckMemory.recordEvent(
          { type: "tool-call", toolName, input },
          observation,
          turn
        );
        recordRecentAction(toolName, input, recentActions);

        await updateInProgress({
          turn,
          timestamp: new Date().toISOString(),
          milestone: milestone.furthest ?? null,
          badges: milestone.badgesObtained,
          badgeNames: milestone.badgeNames,
          screenshot: observation.screenshot.data,
          status: {
            frame: observation.status.frame,
            gameTitle: observation.status.gameTitle,
            gameCode: observation.status.gameCode,
          },
          systemPrompt: SYSTEM_PROMPT,
          observationText,
          claudeText,
          actionPlan: extractActionPlan(claudeText),
          toolCalls: [...toolCallsThisTurn],
          supervisorInterventions: [...supervisorInterventions],
          contextMessages: agent.messageCount,
          error: null,
          durationMs: Date.now() - turnStart,
        });

        return result;
      },
      onEvent: (event) => {
        if (event.type === "text" && event.text?.trim()) {
          claudeText += event.text;
          const preview = event.text.trimStart().slice(0, 120);
          console.log(
            `  [Claude] ${preview}${event.text.length > 120 ? "…" : ""}`
          );
        }
      },
    });
  } catch (error) {
    turnError = error instanceof Error ? error.message : String(error);
    console.error(`[Error] Turn failed: ${turnError}`);
    await sleep(1000);
  }

  console.log(`  [Context] ${agent.messageCount} messages in history`);

  await recordTurn({
    turn,
    timestamp: new Date().toISOString(),
    milestone: milestone.furthest ?? null,
    badges: milestone.badgesObtained,
    badgeNames: milestone.badgeNames,
    screenshot: observation.screenshot.data,
    status: {
      frame: observation.status.frame,
      gameTitle: observation.status.gameTitle,
      gameCode: observation.status.gameCode,
    },
    systemPrompt: SYSTEM_PROMPT,
    observationText,
    claudeText,
    actionPlan: extractActionPlan(claudeText),
    toolCalls: toolCallsThisTurn,
    supervisorInterventions: [...supervisorInterventions],
    contextMessages: agent.messageCount,
    error: turnError,
    durationMs: Date.now() - turnStart,
  });
}

function recordRecentAction(
  toolName: string,
  input: unknown,
  recentActions: string[]
): void {
  const controlTools = [
    "mgba_tap",
    "mgba_tap_many",
    "mgba_hold",
    "mgba_hold_many",
    "mgba_release",
  ];
  if (!controlTools.includes(toolName)) return;

  recentActions.push(`${toolName.replace("mgba_", "")}: ${JSON.stringify(input)}`);
  recentActions.splice(0, Math.max(0, recentActions.length - 10));
}
