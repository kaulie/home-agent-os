# Service: xiaomi.tv.display

小米电视 S Pro 投屏插件（`xiaomi-tv-display`），group=`display`。  
用局域网 **DLNA AVTransport** 把图投到电视，wire 仍是 `display.photo` / `display.slideshow`。

国内澎湃 OS 电视通常没有 Google Cast。本插件是 Cast 的显示后端替换，不是新的 capability 名。

设置 `MAC_EDGE_DISPLAY_BACKEND=xiaomi`（或配置 `MAC_EDGE_XIAOMI_TV_HOST` / `MAC_EDGE_XIAOMI_TV=1`）后，laptop 广告 `xiaomi.tv.display` 而不广告 `chromecast.display`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `xiaomi-tv-display` |
| service_id | `xiaomi.tv.display` |
| group | `display` |
| wire capability | `display.photo` / `display.slideshow` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.xiaomi_tv_display`） |

## 契约

与 [`chromecast-display`](../chromecast-display/capability.md) 相同：`display.photo` 必填 `asset_ref`；`display.slideshow` 必填 `asset_refs`。本步必须带已 resolve 的 AssetRef，禁止从前序 step 自己捡。

电视需开启无线投屏 / DLNA，与 Mac 同一局域网；图片 URL 必须是电视能拉的 LAN 地址。

## 入口

- Mac：`mac/src/mac_edge/plugins/xiaomi_tv_display.py`；`services.py` 按 `display_backend()` 广告
- 可选：`MAC_EDGE_XIAOMI_TV_HOST`、`MAC_EDGE_XIAOMI_TV_NAME`
