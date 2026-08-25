# iPhone light.set 预录音频

与 Mac 同名：`wake` / `on` / `off` + `.m4a|.wav|.mp3|.caf|.aiff`

1. **打进 App**：把文件放在本目录，然后执行：
   ```bash
   cd ios/LivingRoomEdge && python3 generate_xcodeproj.py
   ```
   再重新编译安装。设置页会显示 wake/on/off 是否已打进 bundle。
2. **或真机目录**：`Documents/LightAudio/` 下放同名文件（无需重编）。

有录音则播放；没有则 TTS。

**常见「没触发」：**

- 录音只放在 Mac 的 `plugins/livingroom-ceiling-light/audio/`，iPhone 不会读到。
- 文件在本目录但未跑 `generate_xcodeproj.py` → 未进 Copy Bundle Resources。
- Brain 把 `light.set` 派给了 home-server（Mac 扬声器响，手机不响）→ 看进度里 `assigned_edge` 是否为本机 `participant_id`。
