import type { GameCommand, GameCommandType } from "./GameCommand";

type Listener = (cmd: GameCommand) => void;

const COOLDOWN_MS: Partial<Record<GameCommandType, number>> = {
  MOVE_LEFT: 80,
  MOVE_RIGHT: 80,
  JUMP: 200,
  SPEED_UP: 400,
  SPEED_DOWN: 400,
};

export class GameCommandBus {
  private listeners = new Set<Listener>();
  private lastAt = new Map<GameCommandType, number>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  dispatch(raw: unknown): boolean {
    const cmd = this.normalize(raw);
    if (!cmd) return false;
    const cd = COOLDOWN_MS[cmd.type] ?? 0;
    if (cd > 0) {
      const prev = this.lastAt.get(cmd.type) ?? 0;
      if (cmd.timestamp - prev < cd) return false;
      this.lastAt.set(cmd.type, cmd.timestamp);
    }
    for (const fn of this.listeners) fn(cmd);
    return true;
  }

  private normalize(raw: unknown): GameCommand | null {
    if (!raw || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    const inner =
      obj.command && typeof obj.command === "object"
        ? (obj.command as Record<string, unknown>)
        : obj;
    const type = String(inner.type || "").toUpperCase();
    const valid = [
      "START",
      "PAUSE",
      "RESUME",
      "RESTART",
      "MOVE_LEFT",
      "MOVE_RIGHT",
      "JUMP",
      "SPEED_UP",
      "SPEED_DOWN",
    ];
    if (!valid.includes(type)) return null;
    const sourceRaw = String(inner.source || "SYSTEM").toUpperCase();
    const source =
      sourceRaw === "VOICE" || sourceRaw === "GESTURE" ? sourceRaw : ("SYSTEM" as const);
    return {
      type: type as GameCommand["type"],
      source,
      timestamp: Number(inner.timestamp || Date.now()),
    };
  }
}

export const commandBus = new GameCommandBus();
