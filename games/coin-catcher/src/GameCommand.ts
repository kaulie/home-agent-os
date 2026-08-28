export type GameCommandType =
  | "START"
  | "PAUSE"
  | "RESUME"
  | "RESTART"
  | "MOVE_LEFT"
  | "MOVE_RIGHT"
  | "JUMP"
  | "SPEED_UP"
  | "SPEED_DOWN";

export type GameCommandSource = "VOICE" | "GESTURE" | "SYSTEM";

export interface GameCommand {
  type: GameCommandType;
  source: GameCommandSource;
  timestamp: number;
}

export const GAME_MESSAGE_CHANNEL = "homeagent.game";

const VALID_TYPES = new Set<string>([
  "START",
  "PAUSE",
  "RESUME",
  "RESTART",
  "MOVE_LEFT",
  "MOVE_RIGHT",
  "JUMP",
  "SPEED_UP",
  "SPEED_DOWN",
]);

export function parseGameCommand(raw: unknown): GameCommand | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const inner =
    obj.command && typeof obj.command === "object"
      ? (obj.command as Record<string, unknown>)
      : obj;
  const type = String(inner.type || "").toUpperCase();
  if (!VALID_TYPES.has(type)) return null;
  const sourceRaw = String(inner.source || "SYSTEM").toUpperCase();
  const source: GameCommandSource =
    sourceRaw === "VOICE" || sourceRaw === "GESTURE" ? sourceRaw : "SYSTEM";
  const ts = Number(inner.timestamp || Date.now());
  return { type: type as GameCommandType, source, timestamp: ts };
}
