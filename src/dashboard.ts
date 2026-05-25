import { writeFile, mkdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DASHBOARD_DIR = join(__dirname, "..", "dashboard");
const STATE_FILE = join(DASHBOARD_DIR, "state.json");
const MAX_HISTORY = 30;

export interface ToolCallRecord {
  name: string;
  input: unknown;
}

export interface TurnRecord {
  turn: number;
  timestamp: string;
  milestone: string | null;
  badges: number;
  badgeNames: string[];
  screenshot: string;
  status: { frame: number | null; gameTitle: string; gameCode: string };
  systemPrompt: string;
  observationText: string;
  claudeText: string;
  actionPlan: string;
  toolCalls: ToolCallRecord[];
  supervisorInterventions: string[];
  contextMessages: number;
  error: string | null;
  durationMs: number;
}

export interface DashboardState {
  meta: { model: string; mgbaUrl: string; startedAt: string };
  current: TurnRecord | null;
  history: TurnRecord[];
  updatedAt: string;
}

let _state: DashboardState | null = null;

export async function initDashboard(meta: DashboardState["meta"]): Promise<void> {
  await mkdir(DASHBOARD_DIR, { recursive: true });
  _state = { meta, current: null, history: [], updatedAt: new Date().toISOString() };
  await _persist();
}

export async function updateInProgress(record: TurnRecord): Promise<void> {
  if (!_state) return;
  if (_state.current && _state.current.turn < record.turn) {
    _state.history.unshift(_state.current);
    if (_state.history.length > MAX_HISTORY) _state.history.pop();
  }
  _state.current = record;
  _state.updatedAt = new Date().toISOString();
  await _persist();
}

export async function recordTurn(record: TurnRecord): Promise<void> {
  if (!_state) return;
  _state.current = record;
  _state.updatedAt = new Date().toISOString();
  await _persist();
}

export function extractActionPlan(text: string): string {
  const match = text.match(/<action_plan>([\s\S]*?)<\/action_plan>/);
  return match ? match[1].trim() : text.trim();
}

async function _persist(): Promise<void> {
  if (!_state) return;
  try {
    await writeFile(STATE_FILE, JSON.stringify(_state));
  } catch {
    // non-fatal
  }
}
