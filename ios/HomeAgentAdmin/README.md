# HomeAgent Admin

口袋里的 **Business Console**：看谁在线，开/关 Role 与 Runtime 能力；查看 Runtime 相关 intent 事件流。

独立 App，不是 Console 的 Tab。直连 Brain，不经过本机 `8788` 代理。

**开发 / Debug / Dev Task** 请用独立 App：[HomeAgent Dev](HomeAgentDev/README.md)。

## 打开工程

```bash
python3 ios/HomeAgentAdmin/generate_xcodeproj.py
open ios/HomeAgentAdmin/HomeAgentAdmin.xcodeproj
```

- 主屏幕名称：`HomeAgent Admin`
- Bundle ID：`com.gaolei.homeagent.admin`
- 最低系统：iOS 16
- Signing：Xcode 里选你的 Team

改完 Swift 文件后重新跑 `generate_xcodeproj.py`。

## 页面

| 页 | 做什么 |
|---|---|
| 节点 | 默认只看在线；点一行进详情。列表和详情都显示注册时间。在线列表每 8 秒刷新 |
| 事件流 | 全屋 Runtime 相关 intent 与响应结果。进入立刻拉一次，之后每 1 分钟刷新；下拉立刻刷新 |
| 详情 | 已声明的 Role + Runtime 能力开关 |
| 管理 | Brain 操作日志（策略开关）；旧 Brain 没有接口时才回退本机记录 |
| 连接 | Brain URL + 可选管理员令牌 |

关掉 Runtime 或某条能力时确认一次。开关只写 Brain 策略表，不改心跳广告。

## API

默认 Brain：局域网 `http://192.168.3.84:9527`。连接页可切到云 `http://115.190.153.53:9527` 或自填地址。

- `GET /api/v1/admin/nodes`
- `POST /api/v1/admin/policy` `{participant_id, target_kind, target_id, enabled}`
- `GET /api/v1/admin/logs?limit=`（默认 100，上限 200）
- `GET /api/v1/admin/intents?limit=&before_id=`（默认 50，上限 100；Runtime 相关 intent + 响应结果）
- 可选头 `X-Admin-Token`（Brain 设了 `BRAIN_ADMIN_TOKEN` 才需要）
