import { createHash } from "node:crypto";
import type { MgbaObservation } from "./observation";

const LOOP_WARNING_THRESHOLD = 5;
const HARD_STUCK_THRESHOLD = 10;

export interface LoopState {
  fingerprint: string;
  loopTurns: number;
  isLooping: boolean;
  isHardStuck: boolean;
}

export class LoopDetector {
  #lastFingerprint = "";
  #loopTurns = 0;

  observe(observation: MgbaObservation): LoopState {
    const fingerprint = computeFingerprint(observation);

    if (fingerprint === this.#lastFingerprint) {
      this.#loopTurns += 1;
    } else {
      this.#loopTurns = 1;
      this.#lastFingerprint = fingerprint;
    }

    return {
      fingerprint,
      loopTurns: this.#loopTurns,
      isLooping: this.#loopTurns >= LOOP_WARNING_THRESHOLD,
      isHardStuck: this.#loopTurns >= HARD_STUCK_THRESHOLD,
    };
  }

  reset(): void {
    this.#loopTurns = 0;
    this.#lastFingerprint = "";
  }
}

export function formatLoopWarning(state: LoopState): string {
  if (!state.isLooping) return "";

  const lines: string[] = [];

  if (state.isHardStuck) {
    lines.push(
      `\nCRITICAL: Identical screen for ${state.loopTurns} consecutive turns. System escape triggered. You MUST try a completely different action next:`
    );
  } else {
    lines.push(
      `\nSTUCK WARNING: Same screen for ${state.loopTurns} turns. You must change your approach:`
    );
  }

  lines.push("- Press B to cancel dialog or exit menu");
  lines.push("- If on name entry screen: navigate to END/결정 with D-pad then press A");
  lines.push("- Press Start to open the game menu");
  lines.push("- Try D-pad navigation then A to confirm a selection");

  return lines.join("\n");
}

function computeFingerprint(observation: MgbaObservation): string {
  const screenshotHash = createHash("sha256")
    .update(observation.screenshot.data)
    .digest("hex")
    .slice(0, 16);

  const state = observation.state;
  if (
    state?.readStatus === "available" &&
    state.mapId !== null &&
    state.position.x !== null &&
    state.position.y !== null
  ) {
    return `${state.mapId}:${state.position.x}:${state.position.y}:${screenshotHash}`;
  }

  return screenshotHash;
}
