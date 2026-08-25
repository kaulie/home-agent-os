# video.live_stream

契约见 [capability.md](capability.md)。下面是第一版联调步骤。

## Mac

```bash
cd mac
source .venv/bin/activate
PYTHONPATH=src python -m mac_edge

curl -s http://127.0.0.1:8790/api/v1/video-live/status
```

码流写在 `mac/data/video-live/<stream_id>.ts`。不要对 ingest 端口再 `ffplay tcp://…`（那个口是给手机推流用的）。

**看画面：** 先在手机上 **Stop Stream**，再转码打开（直播过程中用 QuickTime 打开会只闪一帧就停）：

```bash
cd mac
./preview_video_live.sh
```

## Console（iPhone HomeAgent）

1. 设置 → 「直播 · 填这里」→ Mac ingest URL，例如 `http://192.168.1.8:8790`
2. 底栏 **互动** → 顶部分段 **直播**
3. 全屏取景后点 **Start Stream**，状态 **LIVE**
4. Mac 用上面脚本看画面
5. **Stop Stream** 或点 X 后两端 idle

## Larix Broadcaster

同一 Mac ingest 口，不经过 Console prepare 时用常驻 **5004**：

- Connection：**MPEG-TS**
- Mode：**TCP**
- Host：Mac 局域网 IP
- Port：`5004`（或 prepare 返回的端口）
- Video：**H.264**（不要 HEVC）
