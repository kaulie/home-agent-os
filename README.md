# 客厅设备中控器

部署在 **Chromecast with Google TV**（Android TV）上的常驻中控：每 **10 秒**轮询远端 HTTP API，拿到指令后控制本机已安装的 **Spotify** / **网易云音乐** 播放。

## 架构

```text
你的手机 / 脚本 / 自动化
        │  POST 入队指令
        ▼
  远端 API 服务器 (FastAPI)
        │  GET 待执行队列
        ▼
 Chromecast TV 上的「客厅中控」App
        │  打开 App + 下发媒体键
        ▼
   Spotify / 网易云音乐
```

## 目录

| 路径 | 说明 |
|------|------|
| `server/` | 指令队列 / Brain API（Python Flask 等） |
| `android/` | Chromecast TV 客户端（Kotlin Android TV）；`android/app-v2` 为 Edge Agent Demo（`living-room-chromecast`） |
| `ios/` | iPhone Edge Agent Demo（`living-room-iphone` + GoPro Skill），见 [`ios/README.md`](ios/README.md) |
| `mac/` | Mac Edge Runtime（注册 / 心跳 / 拉 intent / Cast 投屏），见 [`mac/README.md`](mac/README.md) |
| `plugins/` | 跨端 Skill / SDK（GoPro、runtime-agent-sdk 等） |

## 1. 启动远端 API

在能被 Chromecast 访问到的机器上（同一局域网），**无需安装第三方依赖**（Python 3.10+）：

```bash
cd server
python3 main.py
```

健康检查：`http://<电脑局域网IP>:8000/health`

### 下发指令

```bash
# 仅歌名
./enqueue.sh play_song netease '披荆斩棘'

# 歌名 + 歌手（歌手可选）
./enqueue.sh play_song netease '晴天 周杰伦'

# 播放 / 暂停 / 下一首 …
./enqueue.sh play spotify
./enqueue.sh next netease
./enqueue.sh pause spotify

# 打开 App，并可带深链
./enqueue.sh launch spotify
./enqueue.sh launch spotify 'spotify:track:3n3AvegLEkuQnqzMxVKLhG'
```

或直接调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/devices/living-room/commands \
  -H 'Content-Type: application/json' \
  -d '{"action":"play_song","app":"netease","song":"披荆斩棘"}'

curl -X POST http://127.0.0.1:8000/api/v1/devices/living-room/commands \
  -H 'Content-Type: application/json' \
  -d '{"action":"play_song","app":"netease","song":"晴天 周杰伦"}'
```

### API 约定

**拉取待执行指令**

`GET /api/v1/devices/{device_id}/commands`

```json
{
  "commands": [
    {
      "id": "cmd-1-ab12cd34",
      "action": "play",
      "app": "spotify",
      "uri": null,
      "created_at": 1710000000.0
    }
  ]
}
```

**确认执行结果（客户端执行后调用，指令才会出队）**

`POST /api/v1/devices/{device_id}/commands/{command_id}/ack`

```json
{ "status": "ok", "message": "play/spotify" }
```

**支持的 `action`**：`play_song` | `launch` | `play` | `pause` | `play_pause` | `next` | `previous` | `stop`

**支持的 `app`**：`netease` | `spotify`

`play_song`：传 `song`（**歌名必填**）。需要时可写成 **`歌名 歌手`**（空格分隔歌手，可选）。

- **顺序**：由 `app` 决定，仅执行对应 App（`netease` 或 `spotify`），**互不 fallback**
- **都失败**：只打日志「播放不成功」，无内置拉流

可选 `uri`：深链（如 `spotify:track:...` 或网易云歌曲链接）。有 `uri` 时会优先用它打开对应 App。

Spotify API 申请（免费）：[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) 创建应用，把 Client ID / Secret 填到中控页。

默认 `device_id` 为 `living-room`，需与 TV 端配置一致。

## 2. 安装 TV 客户端

本机需安装 [Android Studio](https://developer.android.com/studio)（含 Android SDK / JDK 17）。

1. 用 Android Studio 打开 `android/` 目录，等待 Gradle Sync。
2. Chromecast TV 开启「开发者选项 → USB 调试 / 网络调试」，用 `adb connect <TV的IP>:5555` 连接。
3. 运行 `app` 模块安装到 TV。
4. 在中控界面填写：
   - **设备 ID**：`living-room`
   - **服务器 Base URL**：`http://<电脑局域网IP>:8000`
5. 点「保存配置」→「启动轮询」（打开 App 也会自动启动服务）。

开机后会通过 `BOOT_COMPLETED` 自动拉起轮询前台服务。

默认轮询间隔在 [`android/app/build.gradle.kts`](android/app/build.gradle.kts) 的 `POLL_INTERVAL_MS = 10000`。

## 3. 播放控制原理

1. 按包名拉起目标 App（必要时打开 `uri`）：
   - Spotify：`com.spotify.tv.android` → `com.spotify.music`
   - 网易云：`com.netease.cloudmusic.tv` → `com.netease.cloudmusic`
2. 短暂等待 App 取得媒体会话后，通过 `AudioManager.dispatchMediaKeyEvent` 发送播放/暂停/上一首/下一首等媒体键。

> 前提：TV 上已安装对应 App，且目标 App 实现了标准 MediaSession（Spotify / 网易云一般支持）。深链能否打开指定歌曲取决于该 TV 版 App 是否处理该 scheme。

## 4. 快速自测

```bash
# 终端 A：起服务
cd server && python3 main.py

# 终端 B：入队
./enqueue.sh play spotify

# TV 上中控约 10 秒内应显示最近指令 OK play/spotify，并开始/恢复播放
```

## 后续可扩展

- 把轮询换成 WebSocket / MQTT，降低延迟
- 增加按键模拟、打开任意包名、Home Assistant 对接
- 用 sideload 工具（如 `adb`）做无 Android Studio 的日常更新
