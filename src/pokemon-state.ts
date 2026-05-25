import type { MgbaHttpClient } from "./mgba-http";

export type PokemonStateReadStatus = "available" | "unavailable";
export type PokemonDirection = "down" | "up" | "left" | "right" | "unknown";

export const BADGE_NAMES = [
  "Boulder",  // Brock, Pewter City
  "Cascade",  // Misty, Cerulean City
  "Thunder",  // Lt. Surge, Vermilion City
  "Rainbow",  // Erika, Celadon City
  "Soul",     // Koga, Fuchsia City
  "Marsh",    // Sabrina, Saffron City
  "Volcano",  // Blaine, Cinnabar Island
  "Earth",    // Giovanni, Viridian City
] as const;

export interface PokemonStateObservation {
  battle: boolean;
  battleResult: number | null;
  battleType: number | null;
  dialogueLike: boolean | "visual-fallback";
  direction: PokemonDirection;
  mapId: number | null;
  menuLike: boolean | "visual-fallback";
  position: {
    x: number | null;
    y: number | null;
  };
  readStatus: PokemonStateReadStatus;
  badges: number;      // bitmask: bit 0=Boulder, 1=Cascade, ..., 7=Earth
  badgeCount: number;
}

const POKEMON_RED_ADDRESSES = {
  battleResult: 0xcf_0b,
  battleType: 0xd0_5a,
  isInBattle: 0xd0_57,
  mapId: 0xd3_5e,
  playerFacing: 0xc1_09,
  xCoord: 0xd3_62,
  yCoord: 0xd3_61,
  badges: 0xd3_56,
} as const;

export async function readPokemonStateObservation(
  client: MgbaHttpClient,
  signal?: AbortSignal
): Promise<PokemonStateObservation> {
  try {
    const [
      mapId,
      yCoord,
      xCoord,
      facing,
      isInBattle,
      battleType,
      battleResult,
      badges,
    ] = await Promise.all([
      client.read8(POKEMON_RED_ADDRESSES.mapId, signal),
      client.read8(POKEMON_RED_ADDRESSES.yCoord, signal),
      client.read8(POKEMON_RED_ADDRESSES.xCoord, signal),
      client.read8(POKEMON_RED_ADDRESSES.playerFacing, signal),
      client.read8(POKEMON_RED_ADDRESSES.isInBattle, signal),
      client.read8(POKEMON_RED_ADDRESSES.battleType, signal),
      client.read8(POKEMON_RED_ADDRESSES.battleResult, signal),
      client.read8(POKEMON_RED_ADDRESSES.badges, signal),
    ]);

    const badgeCount = countBits(badges);

    return {
      battle: isInBattle !== 0,
      battleResult,
      battleType,
      dialogueLike: "visual-fallback",
      direction: formatDirection(facing),
      mapId,
      menuLike: "visual-fallback",
      position: { x: xCoord, y: yCoord },
      readStatus: "available",
      badges,
      badgeCount,
    };
  } catch {
    return unavailablePokemonStateObservation();
  }
}

export function formatPokemonStateObservation(
  state: PokemonStateObservation
): string {
  const obtainedBadges = BADGE_NAMES.filter(
    (_, i) => (state.badges >> i) & 1
  ).join(", ");

  return [
    `readStatus: ${state.readStatus}`,
    `mapId: ${formatNullableNumber(state.mapId)}`,
    `position: x=${formatNullableNumber(state.position.x)}, y=${formatNullableNumber(state.position.y)}`,
    `direction: ${state.direction}`,
    `battle: ${state.battle}`,
    `battleType: ${formatNullableNumber(state.battleType)}`,
    `battleResult: ${formatNullableNumber(state.battleResult)}`,
    `dialogueLike: ${state.dialogueLike}`,
    `menuLike: ${state.menuLike}`,
    `badges: ${state.badgeCount}/8 (${obtainedBadges || "none"})`,
  ].join("\n");
}

function unavailablePokemonStateObservation(): PokemonStateObservation {
  return {
    battle: false,
    battleResult: null,
    battleType: null,
    dialogueLike: "visual-fallback",
    direction: "unknown",
    mapId: null,
    menuLike: "visual-fallback",
    position: { x: null, y: null },
    readStatus: "unavailable",
    badges: 0,
    badgeCount: 0,
  };
}

function formatDirection(value: number): PokemonDirection {
  if (value === 0) return "down";
  if (value === 4) return "up";
  if (value === 8) return "left";
  if (value === 12) return "right";
  return "unknown";
}

function formatNullableNumber(value: number | null): string {
  return value === null ? "unknown" : String(value);
}

function countBits(n: number): number {
  let count = 0;
  let v = n;
  while (v) {
    // biome-ignore lint/suspicious/noBitwiseOperators: bit count is intentional
    count += v & 1;
    // biome-ignore lint/suspicious/noBitwiseOperators: bit count is intentional
    v >>= 1;
  }
  return count;
}
