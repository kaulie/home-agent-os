import { GAME_MESSAGE_CHANNEL, parseGameCommand } from "./GameCommand";
import { commandBus } from "./GameCommandBus";

/** Receive GameCommand forwarded from Cast Receiver iframe parent. */
export function startCastTransport(): void {
  window.addEventListener("message", (ev) => {
    const data = ev.data;
    if (!data || typeof data !== "object") return;
    const msg = data as Record<string, unknown>;
    if (msg.channel !== GAME_MESSAGE_CHANNEL) return;
    const cmd = parseGameCommand(msg);
    if (cmd) commandBus.dispatch(cmd);
  });

  // Signal ready to parent (Cast Receiver).
  if (window.parent !== window) {
    window.parent.postMessage(
      { channel: GAME_MESSAGE_CHANNEL, event: "game.loaded", game_id: "coin_catcher" },
      "*"
    );
  }
}
