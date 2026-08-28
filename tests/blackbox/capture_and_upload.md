# camera.capture_and_upload（composite）黑盒观察

对标 cloud Brain intent **1450**：拍照派到 Android（iPhone `camera.capture` unavailable），上传却派回 iPhone，本机 `capture_ref` 跨机失败。

## 期望

- Runtime 心跳 **同时** 上报三条：`camera.capture`、`asset.upload`（`composition=atomic`）、`camera.capture_and_upload`（`composition=composite`，`decomposes_to=["camera.capture","asset.upload"]`，有 `prefer_when`）。
- `POST /api/v1/intent` 正文 `拍张照片我看一下`：`execution_plan` **仅一步** `camera.capture_and_upload`，`assigned_edge_id` 为当时 capture available 的节点。
- 不得出现 capture@Android + upload@iPhone。
- 成功后 `GET /api/v1/intent_detail`：`presentation.type=image`，`from=asset_ref`，有 `asset_id`。
- `把刚才那张传到云上` 仍可只派 `asset.upload`。

## 自动化（本机单测，不打现场相机）

2026-08-26 用 `server/.venv` / `mac/.venv` 跑过，均 **ok**：

| 层 | 测试 | 结果 |
|----|------|------|
| Brain sanitize 折叠 | `test_sanitize_folds_capture_upload_into_composite` | 跨边 capture+upload → 一步 composite，派 android-1 |
| Brain 选边 | `test_do_execution_plan_assigns_composite_to_available_runtime` | iPhone capture=false → composite 在 android-1 |
| Brain 入队拒绝拆边 | `test_do_execution_plan_rejects_split_capture_upload` | 无 composite 且 capture/upload 分边 → `CaptureUploadSplitError` |
| Brain 无 composite 不折叠 | `test_sanitize_does_not_fold_without_composite_provider` | 保留两步 atomic |
| Brain catalog | `test_catalog_includes_composite_composition_fields` | android 行带 `composition` / `decomposes_to` / `prefer_when` |
| Brain LLM 管道 | `test_process_llm_task_folds_split_capture_upload` | mock Ark 吐两步 → 入队一步 composite@android-1 |
| Brain 独立上传 | `test_sanitize_keeps_standalone_upload` | 「把刚才那张传到云上」仍 `asset.upload` |
| planner prompt | `test_planner_prompt_does_not_name_capabilities` / `test_planner_prompt_trusts_structured_capability_ads` | 有 `prefer_when`/`decomposes_to`/`composition`；**不点名** `camera.capture_and_upload` |
| Mac Runtime | `mac/tests/test_capture_and_upload_composite.py` | 成功只回 `asset_ref`；上传失败文案带「拍照成功…但」；快门失败不带该前缀 |
| Mac availability | `test_capture_and_upload_unavailable_when_capture_is` | capture 不可用 → composite 不可用（AND） |

Runner：`tests/blackbox/run_suite.py` 已加 **C10c** `拍张照片我看一下`。现场快门仍须 `@quality` 打对外 API（P2，会动相机）。

## 现场 C10c（快门）

未在本轮对 LAN `127.0.0.1:9527` POST 该句：当时进程仍是旧 Brain；`GET /api/v1/capabilities` 无 `camera.capture`（GoPro 未进 schedulable map），且 P2 会动相机。Runtime 需带新心跳后再跑 `cases.md` C10c。

2026-08-26 09:43 已 rsync Brain 到云并 `systemctl restart doubao_skill`。云 `GET /api/v1/capabilities`：全部 23 行带 `composition=atomic`；当时 **没有** `camera.capture` / `camera.capture_and_upload`（GoPro 未进 schedulable map）。composite 要等 Android/iOS/Mac 新心跳上报后才会进 catalog。
