# light.set 预录音频

把你自己录好的唤醒/指令放进本目录（Mac home-server 默认可读；也可设 `MAC_EDGE_LIGHT_AUDIO_DIR` 指向别处）。

| 文件名（任选一扩展名） | 用途 |
|------------------------|------|
| `wake.*` | 唤醒，例如「小书 小书」 |
| `on.*` | 开灯指令 |
| `off.*` | 关灯指令 |

支持扩展名：`.m4a`、`.wav`、`.mp3`、`.caf`、`.aiff`

**有文件 → 播放录音；缺文件 → 本机 TTS 念对应文案。**

iPhone：把同名文件放进 App 内 `Light/Audio/`，或真机 `Documents/LightAudio/`（无需改代码路径）。
