# Reading Agent（指字认字）交接文档

更新时间：2026-08-25 14:32 (UTC+8)
交接原因：用户重启 agent，由新 agent 接手处理泛化测试。

---

## 1. 项目背景

**任务**：Reading Agent V1（静态图指字认字）。用户用手指指向书本/练习册上的某个汉字，系统识别指尖所指的那个字。
**仓库**：`/Users/gaolei/Projects/smart_home_control`
**服务目录**：`character-service/`
**云部署**：`ssh cloud-server`，项目根 = `/root/chat-gateway`（见 `.cursor/rules/cloud-deploy.mdc`）

## 2. 架构（4 阶段 pipeline）

1. **指尖检测**：`hands.py`，MediaPipe Hands，输出食指 origin(指尖) + direction(食指单位向量)。含 EXIF 朝向、多尺度/多置信度检测。
2. **裁块喂 VLM**：`pipeline.py`，双窗口(600,0)/(600,260) × 双跑 + 1 次复核 re-OCR，每图最多 5 次 VLM 调用。
3. **VLM 出候选**：`hunyuan_ocr.py` → llama-server(HunyuanOCR-1.5 GGUF)。行级 OCR，输出 JSON 行块(text+bbox，坐标归一化[0,1000]→像素)。**无单字 spotting、无置信度**。
4. **几何排序**：`geometry.py`，行块拆单字 → 按指尖射线/锥 + lateral 评分排序 → 裁决(top1/top3/status)。

关键文件：`character-service/{hands.py,geometry.py,pipeline.py,hunyuan_ocr.py,ocr_client.py,main.py}`

## 3. 当前云上状态（已验证）

- **Q4 llama-server：健康**。`http://127.0.0.1:8082/health` → `{"status":"ok"}`，pid 174783，`ctx-size=2048`，n_slots=4。
- **character-service 容器**：`home-agent-character`，Up healthy，对外 `http://127.0.0.1:9189/v1/point_to_character`。
- 内存：7G 总 / 4G 用 / 3G 可用。
- **Q8 模型已下载但未启用**：`/root/hunyuan-gguf/HunyuanOCR.Q8_0.gguf`，启动脚本 `/tmp/start_hunyuan_q8.sh`（ctx 1536）。
- Q4 启动脚本：`/root/start_hunyuan.sh`；后台启动辅助：`/root/start_q4_bg.sh`。
- **生产模型 = Q4**（Q8 已评估并判定劣于 Q4，见下）。

## 4. Q4 vs Q8 评估结论（已完成）

6 图 × 5 轮稳定性测试，replay 全量落盘。

| 模型 | top1 | top3 | VLM检出 | 拆字 | 总轮次 |
|---|---|---|---|---|---|
| **Q4** | **30/30 (100%)** | **30/30 (100%)** | 30/30 | 30/30 | 30 |
| Q8 | 24/29 (80%) | 26/29 (87%) | 29/29 | 29/29 | 29(7832 r1 超时) |

**关键规律**：两模型唯一差异是 **8022**（正确=因）。
- Q4：top1=因，5/5 全对。
- Q8：top1=《，**0/5**；「因」5/5 被 VLM 检出、5/5 被拆字检出，但**5 轮全卡在 #3**（lateral ~0.86），被「《」的 ray 命中(~0.996)压过。
- 即 Q8 失败是**纯几何排序问题**，不是 VLM 漏检。Q8 的行框分布让「《」box 落在射线上。
- Q8 还慢 3-4 倍 + 内存压力大 + 1 次超时。

**判定：保留 Q4 为生产模型，Q8 不启用。**（用户已同意「先不调 Q8 几何」。）

## 5. 归档位置

- `character-service/eval/q4/`：Q4 基线（README + stability.log + stability_raw.json + replay/30份 + per_image/6份）
- `character-service/eval/q8/`：Q8 评估（README + log + raw + replay/29份 + per_image/6份）
- `character-service/eval/q4_vs_q8_summary.md`：横向总表 + 结论
- `character-service/eval/q4/per_image/IMG_*.md`、`character-service/eval/q8/per_image/IMG_*.md`：逐图分析（指尖稳定性/逐轮明细/规律小结）
- git tag `q4-baseline`（commit 1e29980）：Q4 冻结版本。
- replay JSON 已去除 `debug_png_base64`（顶层 + replay 层），几何 replay 不需要；要看叠加图可拿原图+坐标重画。
- 注：`character-service/samples/` 在 `.gitignore` 内，不入库。

## 6. 当前任务（待接手）：泛化测试

用户原话：「我觉得先不用调（Q8 几何），我又找了一些图片，我们看下目前的泛化效果如何」。

**待办**：
1. 用户会提供一批新图（尚未放到 samples 目录；截至交接时 `character-service/samples/` 仍只有原 6 张：IMG_7832/8022/8023/8024/8025/8026）。
2. 新图到位后：传到云 `/tmp/`（参考历史：`scp` 或 docker cp 进 `home-agent-character` 容器，容器内路径曾用 `/tmp/IMG_xxxx.jpg`）。
3. 用 Q4（当前已起）跑泛化测试。复用脚本：
   - 单图快速测：见历史 `test_chars.py` / 冒烟脚本（POST `http://127.0.0.1:9189/v1/point_to_character`，body `{"image_base64":...,"return_debug":true}`）。
   - 多轮稳定性 + replay 落盘：`/tmp/stability_test.py`（云上），改 `IMGS` 列表为新图+正确答案，`OUTDIR` 改成如 `/tmp/replay_gen/`。
4. 验收口径：正确答案在 top-3 即通过；记录 top1/top3/耗时/VLM检出/拆字/正确字排名。
5. 用户没给新图的「正确答案」前，先跑出 top1/top3 让用户核对；拿到正确答案后再做逐图分析（复用 `/tmp/build_per_image.py`）。

## 7. 已知坑 / 经验

- **SSH 长连接会被 reset**：VLM 冷调用 ~45s(Q4)/~180s(Q8)，单次 ssh 同步等结果易断连。**用 nohup 落盘 + 轮询日志**，别同步等。
- **stdout 缓冲**：nohup 跑 python 时 print 被 buffer，日志可能空；以 **replay 文件计数**为可靠进度信号。
- **OOM**：Q4 常驻 ~4-5G/7G；Q8 更紧。跑大批量前看 `free -g`，必要时停 `ollama` 容器(`docker stop ollama`)。
- **EXIF 朝向**：原图(尤其 HEIC/iPhone)裁块前必须先 apply EXIF orientation，否则手指方向/字位置全错（8022 当初栽过）。
- **VLM 非确定性**：同一图多次调用行框会变；故用多轮测稳定性。Q4 上 6 图 30 轮 100% 说明几何对 VLM 抖动鲁棒。
- **scp 进 repo 受 auto-review 限制**：归档 replay 到 `character-service/eval/` 时会被拦，需走 smart_mode_approval（用户已批过同类 Q4/Q8 归档）。
- **几何调参原则**（见 `.cursor/rules/capability-independent.mdc`、`qc-design-charter.mdc`）：capability 只看本步入参；VLM 原始 JSON 即契约，不兜底拆包。

## 8. 关键命令速查

```bash
# Q4 健康
ssh cloud-server 'curl -s http://127.0.0.1:8082/health'
# character-service 健康
ssh cloud-server 'curl -s http://127.0.0.1:9189/health'
# 重启 Q4
ssh cloud-server '/root/start_q4_bg.sh'
# 单图调用（云上 python）
ssh cloud-server 'python3 -c "import base64,json,urllib.request; b=base64.b64encode(open(\"/tmp/IMG_xxxx.jpg\",\"rb\").read()).decode(); r=urllib.request.Request(\"http://127.0.0.1:9189/v1/point_to_character\",data=json.dumps({\"image_base64\":b,\"return_debug\":True}).encode(),headers={\"Content-Type\":\"application/json\"}); print(json.loads(urllib.request.urlopen(r,timeout=400).read())[\"character\"])"'
# 离线几何 replay（不重跑 VLM）
python3 -c "import json; from character_service.geometry import rank_characters; d=json.load(open('character-service/eval/q4/replay/IMG_8022_r1.json')); r=d['replay']; print(rank_characters(r['chars'],tuple(r['origin']),tuple(r['direction']),max_angle_deg=r['max_angle_deg'],max_distance=r['max_distance'])[:3])"
```

## 9. 未决问题

- 新泛化图尚未到位（等用户）。
- 新图正确答案需用户确认（部分图可能多解，如 8023=娘/姑、8025=剧/本）。
- 若泛化出现新失败 case，按 4 阶段诊断（指尖→裁块→VLM→几何），优先用 replay 离线调几何，不轻易动 VLM/换模型。
