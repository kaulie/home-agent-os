# Service: local.voice（capability: voice.stream）

常驻语音流入口（`kind=input`），托管在客厅 Mac Runtime 上。

- **不是**独立 Participant / 独立 edge
- 可独立进程（`python -m mac_voice`），由 `mac_edge` 监督或手动与 Runtime 共用 `edge_id`
- **有权** `POST /api/v1/intent`（因 `kind=input`；action/output 不得自行调 intent）；`participant_id` = 托管 Mac 的 `edge_id`
- 权限跟 `kind` 走，不另签 mic edge；Mac 心跳可附带轻量 `intent_sources` 作兼容
- 生命周期自管理：`MAC_VOICE_LISTEN_MODE=wake_word`（默认）须听到唤醒词 **面条 面条** 才 POST intent；`always_on` 仍可调试（任意语音都发）；`wait_command` 一期未实现，不会静默开麦

## Wire

| 字段 | 值 |
|------|-----|
| service_id | `local.voice` |
| capability_id | `voice.stream` |
| kind | `input` |

## 行为

1. 初始化进入系统后按 listen_mode 开麦（默认 wake_word：USB 麦常开，未唤醒不发 intent）
2. 能量切句 → STT → 唤醒门（面条 ×2）→ 可选 POST intent
2b. **Home Mic 合流**：iPhone 直连本机 HAP1 ingest（默认 `0.0.0.0:8792`），重采样 16 kHz 后进入同一套切句 / STT / 唤醒。身份来自 iPhone Runtime 心跳登记的 `participant_id`（HAP1 hello 带上），不是写死的 `usb_mic`/`home_mic` 频道名。`source_context.device_id` / `input_participant_id` = 说话那台 Runtime；`ingress` 仅标记传输（`mac_usb` | `phone_hap1`）；`voice_host_participant_id` = 跑 STT 的 Mac。**不经 Brain 转 PCM**；Brain 只接收 STT 后的 Intent
2c. **唤醒窗按 Input Source 隔离**（默认）：`WakeGatePool` 以 `input_participant_id` 为键（空则回退 `ingress`）。USB 唤醒后，Home Mic 在 5s 内不说唤醒词不能蹭窗下发；反之亦然。喇叭「又咋了」仍共享，约 1.5s debounce。回滚：`MAC_VOICE_WAKE_SCOPE=global`。`always_on` 无 gate，行为不变。
3. **不要**作为用户任务的计划逐步执行；误派则失败并带可读 msg

唤醒应答是本机回复语，**不进入意图理解**：`mac_voice` 在本地 `say`「我在呢」（可在管理页或 Brain 配置），不建 intent、不跑规划器。`POST /api/v1/voice/wake` 若仍被调用，Brain 只确认 wake 事件、**不落 job**。麦回录的整句应答也不会 `POST /api/v1/intent`。普通播报仍用 `notify.speak`。正文指令仍走 `POST /api/v1/intent`。

同一句里只要出现两次 `面条`（或近音，中间可夹其它词）就算唤醒。唤醒句不 POST 剩余词。喇叭回完「又咋了」之后，用户再说的下一句若开口距**回复结束**不足 5 秒，整句作为本轮指令；回复还没说完时开口的不算指令（含喇叭回声被听成「拍照」等）。麦回录的「又咋了」会丢掉，且不延长 5 秒窗。STT 近音别名：miantiao / 棉条 / 面跳 / 免条。火山 STT 关闭口语顺滑（`enable_ddc`），避免「面条面条」被收成一遍；若仍只听出一遍、但这句只有唤醒词且时长 ≥1.1s（`MAC_VOICE_DOUBLE_WAKE_MS`），仍按两遍计。

## 配置

| 变量 | 含义 |
|------|------|
| `MAC_EDGE_VOICE` | `1`/`0` 是否广告并监督（laptop 默认开） |
| `MAC_VOICE_LISTEN_MODE` | `wake_word`（默认）/ `always_on` / `wait_command` |
| `MAC_VOICE_WAKE_SCOPE` | `participant`（默认，按说话人隔离唤醒窗）/ `global`（旧：各路共享一窗） |
| `MAC_VOICE_WAKE_WORD` | 唤醒词，默认 `面条` |
| `MAC_VOICE_WAKE_REPEAT` | 须重复次数，默认 `2` |
| `MAC_VOICE_WAKE_ALIASES` | 逗号分隔近音（默认 `miantiao,棉条,面跳,免条`） |
| `MAC_VOICE_COMMAND_WINDOW_MS` | 「又咋了」说完后，下一句须在此时长内开口，默认 `5000` |
| `MAC_VOICE_PARTIAL_WAKE_MS` | 两遍之间最大间隔，默认 `2500` |
| `MAC_VOICE_DOUBLE_WAKE_MS` | 一句里 STT 只出一遍唤醒词时，语音时长达到此值仍按两遍计，默认 `1100` |
| `MAC_VOICE_WAKE_ACK` | 唤醒成功后喇叭回复，默认 `我在呢`；未设时从 Brain `GET /api/v1/voice/settings` 读取 |
| `MAC_VOICE_SILENCE_MS` | 句末静音多久才切句送 STT，默认 `1000`（中间停顿少于 1 秒并成一句） |
| `MAC_VOICE_STT_WAV_DIR` | STT 输入 wav 目录；空=系统临时目录；`default`=`MAC_VOICE_DATA_DIR/stt_wav` |
| `MAC_VOICE_STT_WAV_KEEP` | `0`（默认）认句后删；`1` 保留（仍按下面策略裁剪） |
| `MAC_VOICE_STT_WAV_MAX_AGE_HOURS` | 固定目录内 wav 最长保留小时，默认 `24`；`0` 关闭 |
| `MAC_VOICE_STT_WAV_MAX_FILES` | 最多保留文件数，默认 `100`；`0` 关闭 |
| `MAC_VOICE_STT_WAV_MAX_MB` | 目录总大小上限 MB，默认 `200`；`0` 关闭 |
| `MAC_EDGE_EDGE_ID` | 父 Runtime id（监督器自动注入） |
| `MAC_VOICE_CLIENT_HINT` | 应与 Runtime 一致（默认 `living-room-mac`） |

## 实现

- Mac：`mac/src/mac_edge/plugins/voice_stream.py`（拒计划步）
- 进程：`mac/src/mac_voice/`
- 监督：`mac/src/mac_edge/voice_supervisor.py`
