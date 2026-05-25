import { BADGE_NAMES, type PokemonStateObservation } from "./pokemon-state";
import type { MgbaObservation } from "./observation";

export const POKEMON_LEAGUE_MILESTONES = [
  "new-game-started",
  "player-control-reached",
  "first-battle-completed",
  "first-pokemon-obtained",
  "badge-1-boulder",   // Brock, Pewter City
  "badge-2-cascade",   // Misty, Cerulean City
  "badge-3-thunder",   // Lt. Surge, Vermilion City
  "badge-4-rainbow",   // Erika, Celadon City
  "badge-5-soul",      // Koga, Fuchsia City
  "badge-6-marsh",     // Sabrina, Saffron City
  "badge-7-volcano",   // Blaine, Cinnabar Island
  "badge-8-earth",     // Giovanni, Viridian City
  "all-badges-obtained",
  "victory-road-entered",
  "elite-four-started",
  "league-cleared",
] as const;

export type PokemonLeagueMilestoneId = (typeof POKEMON_LEAGUE_MILESTONES)[number];

const BADGE_MILESTONES: PokemonLeagueMilestoneId[] = [
  "badge-1-boulder",
  "badge-2-cascade",
  "badge-3-thunder",
  "badge-4-rainbow",
  "badge-5-soul",
  "badge-6-marsh",
  "badge-7-volcano",
  "badge-8-earth",
];

const milestoneRanks = new Map<PokemonLeagueMilestoneId, number>(
  POKEMON_LEAGUE_MILESTONES.map((m, i) => [m, i])
);

export interface MilestoneSnapshot {
  furthest: PokemonLeagueMilestoneId | null;
  badgesObtained: number;
  badgeNames: string[];
}

export class PokemonLeagueMilestoneTracker {
  #furthest: PokemonLeagueMilestoneId | null = null;
  #previousState: PokemonStateObservation | undefined;
  #previousBadges = 0;

  observe(observation: MgbaObservation): MilestoneSnapshot {
    const state = observation.state;
    if (state?.readStatus === "available") {
      this.#checkBadgeMilestones(state);
      this.#checkGameMilestones(state);
      this.#previousState = state;
      this.#previousBadges = state.badges;
    }
    return this.snapshot();
  }

  snapshot(): MilestoneSnapshot {
    const state = this.#previousState;
    const badges = state?.badges ?? this.#previousBadges;
    const badgeNames = BADGE_NAMES.filter((_, i) => (badges >> i) & 1);
    return {
      furthest: this.#furthest,
      badgesObtained: badgeNames.length,
      badgeNames,
    };
  }

  #checkBadgeMilestones(state: PokemonStateObservation): void {
    if (state.badgeCount === 0) return;

    // Check each badge bit
    for (let i = 0; i < 8; i++) {
      // biome-ignore lint/suspicious/noBitwiseOperators: badge bitmask check
      const hasNewBadge = (state.badges >> i) & 1;
      // biome-ignore lint/suspicious/noBitwiseOperators: badge bitmask check
      const hadBefore = (this.#previousBadges >> i) & 1;
      if (hasNewBadge && !hadBefore) {
        const milestone = BADGE_MILESTONES[i];
        if (milestone) this.#advance(milestone);
      }
    }

    if (state.badgeCount === 8) {
      this.#advance("all-badges-obtained");
    }
  }

  #checkGameMilestones(state: PokemonStateObservation): void {
    if (
      state.mapId === null ||
      state.position.x === null ||
      state.position.y === null
    ) {
      return;
    }

    if (this.#previousState?.battle && !state.battle) {
      this.#advance("first-battle-completed");
    }

    if (isPlayerControlState(state)) {
      this.#advance("player-control-reached");
    } else if (state.menuLike === true) {
      this.#advance("new-game-started");
    }
  }

  #advance(milestone: PokemonLeagueMilestoneId): void {
    if (isAfter(milestone, this.#furthest)) {
      this.#furthest = milestone;
    }
  }
}

function isPlayerControlState(state: PokemonStateObservation): boolean {
  return (
    !state.battle &&
    state.dialogueLike !== true &&
    state.menuLike !== true &&
    state.direction !== "unknown"
  );
}

function isAfter(
  candidate: PokemonLeagueMilestoneId,
  current: PokemonLeagueMilestoneId | null
): boolean {
  if (!current) return true;
  return (milestoneRanks.get(candidate) ?? -1) > (milestoneRanks.get(current) ?? -1);
}
