import Phaser from "phaser";
import type { GameCommand, GameCommandType } from "../GameCommand";
import { commandBus } from "../GameCommandBus";

type GameState = "idle" | "playing" | "paused" | "gameover";

interface FallingCoin {
  sprite: Phaser.GameObjects.Arc;
  vy: number;
}

export class CoinCatcherScene extends Phaser.Scene {
  private state: GameState = "idle";
  private score = 0;
  private player!: Phaser.GameObjects.Rectangle;
  private playerBody!: Phaser.Physics.Arcade.Body;
  private coins: FallingCoin[] = [];
  private spawnTimer = 0;
  private spawnInterval = 900;
  private moveLeftUntil = 0;
  private moveRightUntil = 0;
  private jumpVy = 0;
  private playerBaseY = 0;
  private scoreText!: Phaser.GameObjects.Text;
  private hintText!: Phaser.GameObjects.Text;
  private statusText!: Phaser.GameObjects.Text;
  private unsub?: () => void;

  constructor() {
    super({ key: "CoinCatcherScene" });
  }

  create(): void {
    const { width, height } = this.scale;

    this.add.rectangle(width / 2, height / 2, width, height, 0x0a1628);

    // Ground line
    this.add.line(0, 0, 0, height - 120, width, height - 120, 0x2a4a6a, 0.8).setOrigin(0);

    this.playerBaseY = height - 180;
    this.player = this.add.rectangle(width / 2, this.playerBaseY, 100, 60, 0xffc857);
    this.physics.add.existing(this.player);
    this.playerBody = this.player.body as Phaser.Physics.Arcade.Body;
    this.playerBody.setCollideWorldBounds(true);
    this.playerBody.setImmovable(true);

    this.scoreText = this.add
      .text(48, 40, "Score: 0", {
        fontFamily: "system-ui, PingFang SC, sans-serif",
        fontSize: "48px",
        color: "#ffffff",
      })
      .setScrollFactor(0);

    this.hintText = this.add
      .text(width / 2, height / 2 - 40, "说：开始游戏", {
        fontFamily: "system-ui, PingFang SC, sans-serif",
        fontSize: "42px",
        color: "#a8d4ff",
        align: "center",
      })
      .setOrigin(0.5)
      .setScrollFactor(0);

    this.statusText = this.add
      .text(width / 2, height - 48, "语音 / 手势控制 · 键盘方向键调试", {
        fontFamily: "system-ui, PingFang SC, sans-serif",
        fontSize: "24px",
        color: "#6688aa",
      })
      .setOrigin(0.5)
      .setScrollFactor(0);

    this.unsub = commandBus.subscribe((cmd) => this.onCommand(cmd));

    this.input.keyboard?.on("keydown-ENTER", () => {
      commandBus.dispatch({ type: "START", source: "SYSTEM", timestamp: Date.now() });
    });
  }

  shutdown(): void {
    this.unsub?.();
  }

  private onCommand(cmd: GameCommand): void {
    const handlers: Record<GameCommandType, () => void> = {
      START: () => this.startGame(false),
      RESTART: () => this.startGame(true),
      PAUSE: () => {
        if (this.state === "playing") {
          this.state = "paused";
          this.hintText.setText("已暂停 · 说：继续");
        }
      },
      RESUME: () => {
        if (this.state === "paused") {
          this.state = "playing";
          this.hintText.setText("");
        }
      },
      MOVE_LEFT: () => {
        this.moveLeftUntil = this.time.now + 400;
      },
      MOVE_RIGHT: () => {
        this.moveRightUntil = this.time.now + 400;
      },
      JUMP: () => {
        if (this.state === "playing" && Math.abs(this.jumpVy) < 10) {
          this.jumpVy = -520;
        }
      },
      SPEED_UP: () => {
        this.spawnInterval = Math.max(400, this.spawnInterval * 0.85);
      },
      SPEED_DOWN: () => {
        this.spawnInterval = Math.min(1600, this.spawnInterval * 1.15);
      },
    };
    handlers[cmd.type]?.();
  }

  private startGame(reset: boolean): void {
    if (reset) this.clearCoins();
    this.score = 0;
    this.scoreText.setText("Score: 0");
    this.spawnInterval = 900;
    this.state = "playing";
    this.hintText.setText("");
    this.player.x = this.scale.width / 2;
    this.player.y = this.playerBaseY;
    this.jumpVy = 0;
    this.spawnTimer = 0;
  }

  private clearCoins(): void {
    for (const c of this.coins) c.sprite.destroy();
    this.coins = [];
  }

  private spawnCoin(): void {
    const margin = 80;
    const x = margin + Math.random() * (this.scale.width - margin * 2);
    const sprite = this.add.circle(x, -20, 22, 0xffd700).setStrokeStyle(3, 0xffaa00);
    this.coins.push({ sprite, vy: 180 + Math.random() * 120 });
  }

  update(_time: number, delta: number): void {
    if (this.state !== "playing") return;

    const dt = delta / 1000;
    const speed = 420;

    if (this.time.now < this.moveLeftUntil) {
      this.player.x -= speed * dt;
    }
    if (this.time.now < this.moveRightUntil) {
      this.player.x += speed * dt;
    }

    this.player.x = Phaser.Math.Clamp(this.player.x, 60, this.scale.width - 60);

    // Jump arc
    this.jumpVy += 980 * dt;
    this.player.y += this.jumpVy * dt;
    if (this.player.y >= this.playerBaseY) {
      this.player.y = this.playerBaseY;
      this.jumpVy = 0;
    }

    this.spawnTimer += delta;
    if (this.spawnTimer >= this.spawnInterval) {
      this.spawnTimer = 0;
      this.spawnCoin();
    }

    const catchY = this.player.y - 20;
    const catchX = this.player.x;
    const catchR = 55;

    for (let i = this.coins.length - 1; i >= 0; i--) {
      const c = this.coins[i];
      c.sprite.y += c.vy * dt;
      const dx = c.sprite.x - catchX;
      const dy = c.sprite.y - catchY;
      if (dx * dx + dy * dy < catchR * catchR) {
        this.score += 10;
        this.scoreText.setText(`Score: ${this.score}`);
        c.sprite.destroy();
        this.coins.splice(i, 1);
        continue;
      }
      if (c.sprite.y > this.scale.height + 40) {
        c.sprite.destroy();
        this.coins.splice(i, 1);
      }
    }
  }
}
