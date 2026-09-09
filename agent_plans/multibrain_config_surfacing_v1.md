# Plan：MultiBrainClient 暴露 config —— 修复 url/local_upload 资产 “Brain URL is missing”

> 落盘：task-54b2ed92 · 开发分支 `fix/task-54b2ed92-multibrain-config` · 交付方式：PR 到 main
> 触发：intent 675「把最新的URL转成PDF」step2 web.scraper 失败，报
> `AssetStorageError: asset ... is url type but Brain URL is missing`。

## 1. 目标

Mac Edge 双 Brain 运行时，executor 传给 AssetManager 的是 `MultiBrainClient`，
而它只有 `_config`、没有暴露 `config`；`asset/manager.py::resolve_for_capability`
对 url / local_upload 资产取 `self._brain.config.brain_base_url` 得到空串 → 抛
“Brain URL is missing”。单 Brain（BrainClient 有 `.config`）与单测不暴露。

本次改动：给 `MultiBrainClient` 增加 `config` 只读属性（返回构造时的共享
`_config`），与 `BrainClient.config` 对齐，使双 Brain 运行时 url/local_upload
资产能拿到 primary Brain base 生成 `/content` URL。

## 2. 已确认决策

| 维度 | 决策 |
|---|---|
| 主改动 | `mac/src/mac_edge/multi_brain.py`：新增 `config` property |
| 语义 | 返回 `self._config`（构造传入，`brain_base_url`=primary） |
| 兼容 | 属性只读、不触发 `_open`，单/双 Brain 行为一致 |
| 测试 | `tests/test_multi_brain_origin.py`（属性）+ `tests/test_asset_manager.py`（经 MultiBrainClient 解析 url 资产） |

## 3. 改动文件

- `mac/src/mac_edge/multi_brain.py`
- `mac/tests/test_multi_brain_origin.py`
- `mac/tests/test_asset_manager.py`

## 4. 验收

- 新单测在未打补丁时复现原错误（`AssetStorageError ... Brain URL is missing`），
  打补丁后返回 `HttpUrlRepresentation`（指向 `.../assets/{id}/content?intent_id=...`）。
- 相关 mac 单测全绿。
