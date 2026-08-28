import Phaser from "phaser";
import { CoinCatcherScene } from "./CoinCatcherScene";

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: "BootScene" });
  }

  preload(): void {
    // Procedural graphics — no external assets required for MVP.
  }

  create(): void {
    this.scene.start("CoinCatcherScene");
  }
}

export const gameConfig: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  parent: "game",
  width: 1920,
  height: 1080,
  backgroundColor: "#0a1628",
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  physics: {
    default: "arcade",
    arcade: { gravity: { x: 0, y: 0 }, debug: false },
  },
  scene: [BootScene, CoinCatcherScene],
};
