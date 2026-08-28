import Phaser from "phaser";
import { gameConfig } from "./scenes/BootScene";
import { startCastTransport } from "./transport/CastTransport";
import { startKeyboardTransport, startSseTransport } from "./transport/SseTransport";

startCastTransport();
startSseTransport();
startKeyboardTransport();

// eslint-disable-next-line no-new
new Phaser.Game(gameConfig);
