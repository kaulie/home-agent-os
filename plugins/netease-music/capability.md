# Service: netease.music

网易云播放插件（`netease-music`），group=`music`。

- **Mac（主路径）**：本机网易云 App + `ncm-cli`。`music.play` 本轮必须有 `song`；`artist` 只用来收窄搜索。Cast `chromecast.display` 不是本能力。
- **Android / iOS**：公开搜索 API + 深链；验收仍以本机出声为准。

## 规划自描述

Planner 从自然语言拆出 `song`（歌名）和可选 `artist`（作者）。Mac plugin 不理解原句，只按 ncm-cli 拼接 `--keyword "十年 陈奕迅"`。

| capability | 能 | 不能 |
|------------|----|------|
| `music.play` | 按歌名播放（可选作者限定） | 无歌名只点歌手；用 query.content / notify.speak 顶替；下载/缓存索引 |
| `music.cache` | 闲时把搜索结果写入本机索引（Mac / ncm-cli） | 播放；下载音频文件（`fetch_audio` 本轮忽略） |
| `music.pause` | 暂停 | 开始播放 |
| `music.resume` | 继续 | 换歌 |
| `music.stop` | 停止 | 开始播放 |
| `music.next` | 下一首 | 指定歌名（用 music.play） |
| `music.previous` | 上一首 | 指定歌名（用 music.play） |

## Mac 执行面

- 入口：`mac/src/mac_edge/plugins/netease_music.py`
- 搜索：`--keyword` 整段一个参数（有作者：`"十年 陈奕迅"`）。
- 歌曲库：`MAC_EDGE_DATA_DIR/ncm_songs.sqlite3` 表 `ncm_songs`（完整 `record_json`）+ `ncm_song_index`（insert-only）+ `ncm_plays`（仅 `music.play` 写）。`music.play` 命中索引则跳过 search；`music.cache` 只 upsert 索引，不 play、不写 `ncm_plays`。
- `music.cache` 分页：`--limit 20` + `--offset` 0/20/40…，页间 sleep 10s；`count` 默认 100、上限 200。`music.play` 仍 `--limit 10`、不分页。
- play 成功：ncm-cli JSON `success: true`（忽略 `[orpheus]` 前缀行）。
- 控制：`pause` / `resume` / `stop` / `next` / `prev`；`stop` 后退出本机音乐联动。
