# Service: netease.music

网易云播放插件（`netease-music`），group=`music`。  
在广告了本服务的 Edge（当前主要是 Android Chromecast / 手机 App）上搜歌并播放。

## 规划自描述

| capability | 能 | 不能 |
|------------|----|------|
| `music.play` | 按 song/album/artist 播放 | 用 query.content / notify.speak 顶替；无本能力时 plan=[] |
| `music.pause` | 暂停 | 开始播放 |
| `music.stop` | 停止 | 开始播放 |
| `music.next` | 下一首 | 指定歌名（用 music.play） |
| `music.previous` | 上一首 | 指定歌名（用 music.play） |
