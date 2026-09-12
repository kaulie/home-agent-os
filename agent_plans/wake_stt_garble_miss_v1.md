# STT 近音漏应答 — v1

## 现象

连续再唤时约 3 次无「我在呢」。日志：`凉凉面条儿` / `调面条条` POST 成 intent；`炒面条` 仅 partial。

## 根因

指令窗内 `hits=1` 且 remainder 非空时被当成命令；`我我在呢` 未进应答回声匹配。

## 修复

- listening/acking：`hits > 0` → partial/重唤，不 POST
- 应答正则认 `我+在呢`
- residual remainder + 时长 ≥ double_wake → hits 升为 2
