# Plan：插拔 USB 麦后免重启（mac_voice 自动重扫 host API）

> 落盘：task-c7cf506e · 开发分支 `fix/task-c7cf506e-usb-mic-rescan` · 交付：PR 到 main
> 触发：用户刚插上 reSpeaker XVF3800（Mac USB 麦）后「还不能说话」，实测确认需要重启
> mac_voice 才行。

## 1. 现象与根因（已实测）

| 观测方 | 看到的输入设备 |
|---|---|
| macOS `system_profiler` | `reSpeaker XVF3800 4-Mic Array`（2ch）✅ |
| **新进程** `sd.query_devices()` | `0:'reSpeaker XVF3800 4-Mic Array'`、`1:'BlackHole 2ch'`、`2:'MacBook Pro麦克风'` ✅ |
| **在跑的 mac_voice**（09:43 启动） | `0:'BlackHole 2ch', 1:'MacBook Pro麦克风'` ❌ 没有 reSpeaker |

mac_voice 日志（16:48:34，**插麦之后**）仍在刷：

```
ValueError: No input device matching 'reSpeaker XVF3800 4-Mic Array';
          available: 0:'BlackHole 2ch', 1:'MacBook Pro麦克风'
ERROR mac_voice.listen: open mic failed; retry in 2s
```

**根因**：PortAudio 的设备表是**进程级快照**。`source.py` 的 `_live_device_list()`
只在「输入设备表**为空**」时才 `_terminate()/_initialize()` 重扫：

```python
if any(d["max_input_channels"] > 0 for d in devices):
    return devices          # ← 表里有 BlackHole/内置麦 → 永远返回旧快照
```

本机表里**不空**，所以自动重扫路径不触发 → 进程启动后才插上的 USB 麦永远发现不了，
`_capture_loop` 只能每 2s 重试失败（日志里从未出现 `mac_usb alive`）。

## 2. 目标

进程存活期间插上的 USB 麦能被自动发现，**免重启**；且不改变现有任何解析语义。

## 3. 方案

只改 `mac/src/mac_voice/audio/source.py`：

1. 抽出 `_query_devices()` / `_has_inputs()` / `_reinit_host_api() -> bool`；
   `_live_device_list()` 行为保持不变（空表才重扫，重扫失败仍然返回旧表）。
2. `resolve_input_device()`：把现有匹配逻辑收成一个内部 `_attempt(catalog)`；
   当**匹配失败**且调用方**没有显式传 `devices=`**（即走真实设备表）时：
   - 重扫一次 host API（`_reinit_host_api()`），
   - 用新设备表再试一次；
   - 重扫失败则保持原样抛错。
3. 显式传 `devices=` 的调用（含全部现有单测）**不触发重扫** → 语义不变、可测。

不改 `listen.py`：它的「open 失败 → 2s 重试」循环天然就是重扫的触发点。

## 4. 契约

- 公开函数签名不变（`resolve_input_device(device, *, devices=None, fallback_index=None)`）。
- 错误文案不变（`no input device; available: …` / `No input device matching …` /
  `(none)` / `no input device <n>`）。
- 唯一行为变化：真实设备表下匹配失败时，会多一次 host API 重扫与重试。

## 5. 改动文件

- `mac/src/mac_voice/audio/source.py`
- `mac/tests/test_mac_voice_audio.py`

## 6. 测试点

- 匹配失败 + 真实设备表 → 重扫一次并命中新插上的 reSpeaker；
- 重扫后仍找不到 → 抛错，且只重扫一次；
- `_reinit_host_api` 失败（`_terminate` 抛异常）→ 保持原错误，不吞异常；
- **显式传 `devices=` 缺失 → 不重扫**（现有 5 例语义不变）；
- 现有 `test_live_query_reinitializes_when_empty`（空表重扫）保持通过。
