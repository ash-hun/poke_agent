import type { MgbaHttpClient, MgbaStatus } from "./mgba-http";
import {
  formatPokemonStateObservation,
  type PokemonStateObservation,
  readPokemonStateObservation,
} from "./pokemon-state";
import { readOptimizedGameBoyScreenshotBase64 } from "./screenshot-image";
import { formatStuckMemory, type StuckMemorySnapshot } from "./stuck-memory";
import { createScreenshotPath } from "./utils";

export interface MgbaObservation {
  screenshot: {
    data: string;
    mediaType: "image/png";
    path: string;
  };
  state?: PokemonStateObservation;
  status: MgbaStatus;
}

export async function captureMgbaObservation(
  client: MgbaHttpClient,
  signal?: AbortSignal
): Promise<MgbaObservation> {
  const screenshotPath = await createScreenshotPath();
  const [status, state] = await Promise.all([
    client.status(signal),
    readPokemonStateObservation(client, signal),
    client.screenshot(screenshotPath, signal),
  ]);
  const data = await readOptimizedGameBoyScreenshotBase64(screenshotPath, {
    overlayGrid: true,
  });

  return {
    screenshot: { data, mediaType: "image/png", path: screenshotPath },
    state,
    status,
  };
}

export function formatObservationText(
  observation: MgbaObservation,
  recentActions: readonly string[],
  stuckMemory: StuckMemorySnapshot | undefined,
  turn: number,
  loopWarning?: string
): string {
  return [
    `Turn ${turn}. Observe the current game state and decide on the best action to progress toward clearing the Pokemon League.`,
    `\nCurrent mGBA status:\n${formatStatus(observation.status)}`,
    formatState(observation.state),
    formatRecentActions(recentActions),
    loopWarning ?? "",
    formatStuckMemory(stuckMemory),
    `\nCurrent screenshot: attached image below. Red grid lines are movement guide lines marking 16x16 Game Boy movement-cell boundaries. Distinguish blocked cells (walls, furniture, solid black) from walkable floor tiles. Dark passages, stairs, mats, and thresholds may be map transitions — approach and test them. Explore open unseen space or face objects and press A to interact.`,
  ]
    .filter(Boolean)
    .join("");
}

export function formatStatus(status: MgbaStatus): string {
  const activeButtons = status.activeButtons.join(", ") || "none";
  return [
    `frame: ${status.frame ?? "unknown"}`,
    `game: ${[status.gameTitle, status.gameCode].filter(Boolean).join(" ") || "unknown"}`,
    `active buttons: ${activeButtons}`,
  ].join("\n");
}

function formatRecentActions(recentActions: readonly string[]): string {
  if (recentActions.length === 0) return "";
  return `\nrecent actions to avoid repeating blindly:\n${recentActions.map((action) => `- ${action}`).join("\n")}`;
}

function formatState(state: PokemonStateObservation | undefined): string {
  if (!state) return "";
  return `\n\nCurrent compact Pokémon state:\n${formatPokemonStateObservation(state)}`;
}
