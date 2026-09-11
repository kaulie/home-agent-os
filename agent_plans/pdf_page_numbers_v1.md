# Plan：web.scraper 生成的 PDF 带页码

> 落盘：task-c7cf506e · 开发分支 `feature/task-c7cf506e-pdf-page-numbers` · 交付：PR 到 main
> 触发：用户问「生成的PDF可以带页码吗」→ 确认要做。

## 1. 目标

`web.scraper` 转出的 PDF 默认带页码。支持两种样式（参数级传入），默认
**「第 N 页 / 共 M 页」**；默认开启；全部页都编号；并保留 Chrome 原生页眉页脚
作为可选开关（默认关）。

**范围**：只改 `web.scraper`。`file.convert`（图片→PDF）本轮不动。

## 2. 已确认决策（用户拍板）

| # | 维度 | 决策 |
|---|---|---|
| 1 | 样式 | **两种都支持**，由参数选；**默认「第 1 页 / 共 3 页」** |
| 2 | 范围 | **只 `web.scraper`** 生效（`file.convert` 不动） |
| 3 | 默认 | 页码**默认开** |
| 4 | 覆盖 | **全部页编号**（不跳过首页/封面） |
| 5 | 原生页脚 | 加开关配置；**保留** `--no-pdf-header-footer` 能力；**默认不要**（默认仍关闭）；**打开时不走盖章逻辑** |

## 3. 实测结论（本机实测，决定了方案形状）

| 实验 | 结果 |
|---|---|
| Chrome `--print-to-pdf` **不带** `--no-pdf-header-footer` | 页脚带 `1/3`，但**强制捆绑 日期 + URL**，样式不可定制 |
| Chrome **带** `--no-pdf-header-footer`（现状） | 无任何页码 |
| Chrome 是否支持 CSS `@page` margin box（`@bottom-center`） | **不支持** → 不能靠注入 @page CSS 出页码 |
| **Chrome** 渲染「第 1 页 / 共 3 页」→ 图片 → OCR | ✅ `第1页/共3页`（正确） |
| **weasyprint** 渲染同一段 40pt 大字 → OCR | ❌ `3` / `1`（**#671 字形错位复现**） |
| Chrome overlay 产物是否含整页填充矩形 | 无 → **透明**，叠加不遮挡正文 |
| pypdf 盖章端到端（Chrome overlay → merge → 渲染图 OCR） | ✅ 同页 `PAGE ONE`(y=96) + `第1页/共3页`(y=1507 居中) 均清晰可读 |

**结论：盖章 overlay 必须用 Chrome 渲染，绝不能用 weasyprint**（weasyprint 在本机
CJK 字形错位，且这在 `auto` 下是默认引擎之外的老问题；用它会盖出乱码页码）。

## 4. 方案

渲染完 PDF 后用 **pypdf 后处理盖章**（引擎无关，但 overlay 用 Chrome 渲染）：

1. 渲染正文 PDF（现有逻辑，`renderer=chrome`，保持 `--no-pdf-header-footer`）；
2. `pdf_page_count()` 拿到总页数 M（已有）；
3. 用 **Chrome** 把一份「M 页、每页只有一条页脚文字」的 HTML 渲染成 overlay PDF：
   - `@page{size:A4;margin:0}` + 每页一个 `height:29.5cm` 的 `.pg`（`page-break-after`），
     页脚 `position:absolute; bottom:1.0cm; text-align:center`；
   - 只画文字、不设背景 → **透明**（已实测无整页填充）；
4. `pypdf`：`page.merge_page(overlay.pages[i])` 逐页叠加，写回临时文件；
5. 再上传登记（现有流程不变）。

### 新增入参

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `page_numbers` | bool | **true** | 默认开；关闭则完全保持现状 |
| `page_number_style` | `cn` / `numeric` | **`cn`** | `cn`=`第 N 页 / 共 M 页`；`numeric`=`N / M` |
| `native_header_footer` | bool | **false** | true → **去掉** `--no-pdf-header-footer`，用 Chrome 原生页脚；**此时跳过盖章**（原生页脚已含 `N/M`，避免重复）。保持现有默认行为不变 |

## 5. 契约变更

`plugins/web-scraper/capability.md`：

- **输入** 增 `page_numbers` / `page_number_style` / `native_header_footer`（仅 `format=pdf` 生效）；
- **输出** 增 `page_numbers`（bool）、`page_number_style`、`native_header_footer`；
- 说明：`format=text` 不受影响；`page_numbers` 默认开。

`mac/src/mac_edge/plugins/web_scraper.py`：

- 新增常量 `PAGE_NUM_STYLE_CN/_NUMERIC` + 别名表（沿用 `_normalize_choice` 风格）；
- 新增 `_as_bool`（对齐 `query_content.py` / `vision_ask.py` 已有的 bool 解析约定）；
- 新增 `build_page_number_overlay_html(total, style)`、`_render_overlay_pdf(total, style, dst)`（走 Chrome）、`stamp_page_numbers(src, dst, total, style)`；
- `_render_chrome(html_file, dst, *, header_footer=False)` 增加开关，透传 `--no-pdf-header-footer`；
- `scrape_from_params` 在 `page_count` 之后、`upload_file` 之前插入盖章步骤；
- `status_text` 带上「带页码」措辞。

## 6. 改动文件

- `mac/src/mac_edge/plugins/web_scraper.py`
- `mac/tests/test_web_scraper.py`
- `plugins/web-scraper/capability.md`

## 7. 测试点（`mac/tests/test_web_scraper.py`）

- 参数解析：`page_numbers` 默认 true / 显式 false；`page_number_style` 默认 `cn`、别名归一、非法值中文失败；
- `page_number_style` 两种取值的页脚文案正确（`第 3 页 / 共 7 页` / `3 / 7`）；
- `page_numbers=false` → **不调用**盖章；
- `native_header_footer=true` → chrome 命令**不**带 `--no-pdf-header-footer`，且**跳过**盖章；
- 盖章调用 pypdf merge（mock），页数不变；
- Chrome 不可用 + `page_numbers=true` → **降级**（跳过盖章 + 输出标注），**不失败**；
- 中文页码文案含全角/半角与空格形式固定（防回归）；
- 现有 43 例保持全绿。

## 8. 待确认（我先按下列默认实现，若不对请直接说）

| # | 点 | 我的默认 |
|---|---|---|
| a | 页码位置 | **页脚居中**（`bottom:1.0cm`，可一行常量改） |
| b | 无 Chrome 环境（只有 weasyprint） | **降级**：跳过盖章、输出 `page_numbers=false` + 说明，**不让整次抓取失败** |
| c | `native_header_footer=true` + `renderer=weasyprint` | weasyprint 无原生页脚 → 视作不可用，**回退到盖章**（不静默丢页码） |
| d | `native_header_footer=true` 时的 `page_number_style` | 无意义（原生页脚样式固定），输出里照实回传、文档标注 |
| e | `format=text` | 完全不涉及 |

## 9. 实施结果与验证（已完成）

| 验证 | 结果 |
|---|---|
| 单测 `tests/test_web_scraper.py` | **61 例全绿**（原 43 + 新增 18） |
| mac 全量 `tests/` | 697 例；仅 3 例失败，且**用 `origin/main` 干净 worktree 复现完全相同** → 既有问题 |
| server `test_home_brain` + `test_system_capabilities` | 192 例；8 例失败，**基线 diff 逐条一致** → 既有问题 |
| 真实链路 E2E（真 Chrome 渲染 + 真盖章，4 页） | 每页页脚正确：`第 1 页 / 共 4 页` … `第 4 页 / 共 4 页` |
| **OCR 视觉验证**（渲染图 → :9188 OCR） | 第 1 页 `第1页/共4页`、第 2 页 `第2页/共4页`，正文完好未遮挡，中文无乱码 |
| `page_number_style=numeric` | `1 / 4` … `4 / 4` |
| `page_numbers=false` | 无任何页脚（= 改动前行为） |
| `native_header_footer=true` | Chrome 原生页脚 `1/4`…`4/4`，**不重复叠加** |
| pypdf 弃用告警 | `-W error::DeprecationWarning` 下全绿（改用「先 `add_page` 再 `merge_page`」，不再踩 7.0 将移除的路径） |

实现要点偏离原计划的只有一处（并已按更稳的写法落地）：`stamp_page_numbers`
**不再就地覆写** `src`，而是写临时文件后 `os.replace` 原子替换 —— 避免 `PdfReader`
仍指向 `src` 时就地写入的文件句柄别名问题。

改动文件（7 个）：

- `mac/src/mac_edge/plugins/web_scraper.py`（主逻辑）
- `mac/tests/test_web_scraper.py`（+18 例）
- `mac/src/mac_edge/services.py`（input/output schema）
- `mac/src/mac_edge/capability_ads.py`（planner_recognize）
- `server/edge_services.py`（协议登记 schema + planner_recognize）
- `server/capability_ads.py`（planner_recognize）
- `plugins/web-scraper/capability.md`（契约文档）
