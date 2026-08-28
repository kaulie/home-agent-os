import { parseGameCommand } from "../GameCommand";
import { commandBus } from "../GameCommandBus";

function sseUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const custom = params.get("sse") || params.get("stream");
  if (custom) return custom;
  return `${window.location.origin}/events/stream`;
}

/** Dev fallback: SSE from Mac serve.py */
export function startSseTransport(): void {
  const params = new URLSearchParams(window.location.search);
  if (params.get("transport") === "cast") return;

  const url = sseUrl();
  let es: EventSource;
  const connect = () => {
    try {
      es = new EventSource(url);
    } catch {
      return;
    }
    es.onmessage = (ev) => {
      const cmd = parseGameCommand(JSON.parse(ev.data));
      if (cmd) commandBus.dispatch(cmd);
    };
    es.onerror = () => {
      es.close();
      window.setTimeout(connect, 1500);
    };
  };
  connect();
}

/** Keyboard debug controls */
export function startKeyboardTransport(): void {
  const map: Record<string, string> = {
    ArrowLeft: "MOVE_LEFT",
    ArrowRight: "MOVE_RIGHT",
    Space: "JUMP",
    KeyP: "PAUSE",
    KeyR: "RESTART",
    Enter: "START",
  };
  window.addEventListener("keydown", (ev) => {
    const type = map[ev.code];
    if (!type) return;
    ev.preventDefault();
    commandBus.dispatch({ type, source: "SYSTEM", timestamp: Date.now() });
  });
}
