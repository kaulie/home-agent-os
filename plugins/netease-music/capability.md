# Service: netease.music

网易云播放插件（`netease-music`），group=`music`。

- **Mac（主路径）**：本机网易云 App + `ncm-cli`。`music.play` 有 `song`/`artist` 时按搜索播放；**两者皆空**时先 `resume`，否则拉每日推荐连播。Cast `chromecast.display` 不是本能力。
- **Android / iOS**：公开搜索 API + 深链；验收仍以本机出声为准。

## 规划自描述

Planner 从自然语言拆出 `song`（歌名）和可选 `artist`（作者）。Mac plugin 不理解原句，只按 ncm-cli 拼接 `--keyword "十年 陈奕迅"`。

| capability | 能 | 不能 |
|------------|----|------|
| `music.play` | 按歌名播放（可选作者限定）；「xxx的歌」或仅 `artist` 时搜同艺人最多 20 首，写入可复用云歌单后 `play --playlist` 连播；**无 song/artist 时先继续播放，否则每日推荐同样走歌单连播** | 无歌名只点歌手（非「xxx的歌」句式）用 query.content；下载/缓存索引 |
| `music.cache` | 闲时把搜索结果写入本机索引（Mac / ncm-cli） | 播放；下载音频文件（`fetch_audio` 本轮忽略） |
| `music.pause` | 暂停 | 开始播放 |
| `music.resume` | 继续；**空队列则改播每日推荐** | 换歌 |
| `music.stop` | 停止 | 开始播放 |
| `music.next` | 下一首 | 指定歌名（用 music.play） |
| `music.previous` | 上一首 | 指定歌名（用 music.play） |

## Mac 执行面

- 入口：`mac/src/mac_edge/plugins/netease_music.py`
- 搜索：`--keyword` 整段一个参数（有作者：`"十年 陈奕迅"`）。
- 歌曲库：`MAC_EDGE_DATA_DIR/ncm_songs.sqlite3` 表 `ncm_songs`（完整 `record_json`）+ `ncm_song_index`（insert-only）+ `ncm_plays`（仅 `music.play` 写）。`music.play` 命中索引则跳过 search；`music.cache` 只 upsert 索引，不 play、不写 `ncm_plays`。
- `music.cache` 分页：`--limit 20` + `--offset` 0/20/40…，页间 sleep 10s；`count` 默认 100、上限 200。`music.play` 仍 `--limit 10`、不分页。
- **歌手连播**：`song` 形如「xxx的歌/歌曲」或仅有 `artist` 时，分页搜该艺人最多 20 首 → 写入本机复用云歌单 `home-agent-now-playing` → `play --playlist`。orpheus 下桌面 `queue add` 会假成功（「队列为空或无法读取」），不能靠它连播。明确歌名（如「十年」「陈奕迅的十年」）仍单次 `play --song`。
- **句首数量词**：`几首`/`几曲`/`一些`/`N首`（阿拉伯数字）不是歌手名的一部分。剥掉后再解析「xxx的歌」；`几首` 类默认连播 5 首，`N首` 按 N（1–20）截断。可选入参 `count` 覆盖上限。
- **空参开播**：`song` 与 `artist` 皆空（如用户只说「播放音乐」）→ 先 `ncm-cli resume`；失败则 `recommend daily`（最多 20 首）走与歌手连播相同的云歌单 `play --playlist`。不依赖 `state`（云音乐模式下不可用）。
- play 成功：单曲看 ncm-cli JSON `success: true`；`play --playlist` 在 orpheus 下可能只有 `[orpheus]` 行、无 JSON，仍视为成功。
- **播放同步录音（默认开）**：`play --song` / 连播开播后用本机 `ffmpeg` 从 `none:BlackHole 2ch` 录到 `{MAC_EDGE_DATA_DIR}/ncm_recordings/`；按时长结束，`stop`/`pause`/`next`/`previous` 也会停。`MAC_EDGE_NCM_RECORD=0` 可关。
- 控制：`pause` / `resume` / `stop` / `next` / `prev`；`stop` 后退出本机音乐联动。
