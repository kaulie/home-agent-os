"""Planner-facing capability ads (structured; not 「能：/不能：」 prose).

Wire fields (heartbeat / CAPABILITY_REGISTRY):
  kind, composition, role, planner_recognize, typical_triggers[], do_not_dispatch[]
plus input_schema / output_schema (filled by services.py).
Composite rows also carry decomposes_to[] and prefer_when.

`kind` is system placement: input | action | output | system.
`composition` is orthogonal: atomic | composite. Missing → atomic.
`system` = Brain-side catalog / inventory (not bound to a Runtime).
`description` is not the planning contract.
"""

from __future__ import annotations

from typing import Any, Literal

Kind = Literal["input", "action", "output", "system"]
VALID_KINDS = frozenset({"input", "action", "output", "system"})
Composition = Literal["atomic", "composite"]
VALID_COMPOSITIONS = frozenset({"atomic", "composite"})

CAPTURE_AND_UPLOAD_PREFER_WHEN = (
    "拍照后还有后续动作要消费这张照片（给人看、变成 Asset、vision、投屏）时，"
    "优先本能力，不要把 decomposes_to 拆成多步"
)
POINT_TO_CHARACTER_PREFER_WHEN = (
    "要认手指指的那个字时，优先本能力，"
    "不要把 decomposes_to 拆成多步，也不要用整页 OCR"
)


def _ad(
    *,
    kind: Kind,
    role: str,
    planner_recognize: str,
    typical_triggers: list[str],
    do_not_dispatch: list[str],
    composition: Composition = "atomic",
    decomposes_to: list[str] | None = None,
    prefer_when: str | None = None,
) -> dict[str, Any]:
    k = str(kind or "").strip().lower()
    if k not in VALID_KINDS:
        raise ValueError(f"invalid capability kind={kind!r}; expected input|action|output|system")
    comp = str(composition or "atomic").strip().lower()
    if comp not in VALID_COMPOSITIONS:
        raise ValueError(
            f"invalid capability composition={composition!r}; expected atomic|composite"
        )
    out: dict[str, Any] = {
        "kind": k,
        "role": role,
        "planner_recognize": planner_recognize,
        "typical_triggers": list(typical_triggers),
        "do_not_dispatch": list(do_not_dispatch),
        "composition": comp,
    }
    if comp == "composite":
        parts = [str(x).strip() for x in (decomposes_to or []) if str(x).strip()]
        if not parts:
            raise ValueError("composite capability requires non-empty decomposes_to")
        when = str(prefer_when or "").strip()
        if not when:
            raise ValueError("composite capability requires prefer_when")
        out["decomposes_to"] = parts
        out["prefer_when"] = when
    return out


# capability_id → planner fields (schemas attached in services.py / edge_services)
# Ads must match the plugin contract and speak household scenes, not abstract labels.
ADS: dict[str, dict[str, Any]] = {
    "voice.stream": _ad(
        kind="input",
        role="常驻语音流入口",
        planner_recognize="客厅/手机上一直开着的麦克风：自己收音、转写，把口语变成意图。这是常驻入口，不是用户任务里的一步，不要排进 plan",
        typical_triggers=["对着麦克风说话", "语音下指令"],
        do_not_dispatch=["作为计划逐步执行", "知识问答", "控制设备", "投屏"],
    ),
    "voicewakeup.echo": _ad(
        kind="output",
        role="唤醒回声",
        planner_recognize="用户喊唤醒词之后，语音入口本机立刻回一句（如「又咋了」）。不是提醒、不是念答案、不是报时，不要排进用户任务计划",
        typical_triggers=["系统内部唤醒回声（非用户指令）"],
        do_not_dispatch=[
            "作为计划逐步执行",
            "普通播报",
            "提醒",
            "念答案",
            "知识问答",
            "控制设备",
            "报时",
        ],
    ),
    "video.live_stream": _ad(
        kind="input",
        role="iPhone 实时视频流入口",
        planner_recognize="把 iPhone 摄像头编成实时视频流推到 Mac。常驻推流，不是拍一张、不是看图问答、不要当 plan 逐步执行",
        typical_triggers=["开始直播", "推摄像头画面"],
        do_not_dispatch=["作为计划逐步执行", "看图理解", "抽帧上传", "投屏"],
    ),
    "game.launch": _ad(
        kind="output",
        role="电视互动游戏启动器",
        planner_recognize="在电视上启动指定互动游戏（接金币等）。本步必填 game_id。启动后实时语音/手势控制不走 Brain，由 iPhone 本地 GameCommand 直送电视",
        typical_triggers=["打开接金币游戏", "玩游戏", "打开电视游戏", "玩接金币", "启动游戏"],
        do_not_dispatch=["向左", "向右", "暂停", "继续", "跳", "实时移动", "帧级控制"],
    ),
    "game.input": _ad(
        kind="input",
        role="游戏语音/手势输入",
        planner_recognize="iPhone 游戏遥控器：本地 ASR + 人体姿态识别，转 GameCommand 直送电视。常驻输入，不是 plan 逐步执行",
        typical_triggers=["游戏遥控器", "挥手玩游戏"],
        do_not_dispatch=["作为计划逐步执行", "知识问答", "投屏单图"],
    ),
    "math.calculate": _ad(
        kind="action",
        role="确定性算术求值器",
        planner_recognize="只算能直接求值的算式（1+1、3×5、根号4），产出数字结果。应用题、单位换算、百科题不要用本步",
        typical_triggers=["1+1等于几", "根号4", "3×5", "一百除以四"],
        do_not_dispatch=["应用题", "复杂数学", "单位换算", "知识问答"],
    ),
    "query.content": _ad(
        kind="action",
        role="文本知识与推理回答器",
        planner_recognize="家里没有对应设备能力时，用文本回答百科/讲解/应用题（为什么天是蓝的、这道题怎么解）。不要当钟、不要看家里的图、不要介绍你会什么、不要投电视。仅当用户明确说「画一张/生成一张图」才走本步生图（AI 文生图，不是搜网上实拍）；生图成功才有 asset_ref",
        typical_triggers=[
            "为什么天是蓝的",
            "这道应用题怎么解",
            "帮我解释一下",
            "画一只猫",
            "生成一张示意图",
            "来张战斗机的图片",
        ],
        do_not_dispatch=[
            "报时",
            "现在几点了",
            "今天几号",
            "墙上几点",
            "看图",
            "拍照",
            "投屏",
            "把这张图投到电视",
            "控制设备",
            "资产盘点",
            "你可以做什么",
            "能力介绍",
            "你会什么",
            "闲聊问候",
            "你可以控制",
            "你会开",
            "搜网上实拍图",
            "文搜图",
            "找真实照片",
            "Openverse检索",
            "必应检索",
            "OCR",
            "读图上的字",
        ],
    ),
    "search.images": _ad(
        kind="action",
        role="互联网实拍图检索器",
        planner_recognize="按关键词去网上搜存量实拍图（必应/Openverse），例如「搜一张故宫的照片」「找几张风景图」。不是 AI 画图，不是拍家里，不是翻本机相册。产出 asset_refs。投电视要另排投屏步",
        typical_triggers=[
            "搜一张猫的照片",
            "找网上的实拍图",
            "搜索故宫的照片",
            "给我找几张风景图",
            "网上搜几张实拍",
        ],
        do_not_dispatch=[
            "AI文生图",
            "画一张",
            "生成图片",
            "知识问答",
            "拍照",
            "看本地相册",
            "投屏本身",
            "OCR",
            "读图上的字",
        ],
    ),
    "image.ocr": _ad(
        kind="system",
        role="图片文字识别器",
        planner_recognize="读已有 Image Asset 上整页/整段印着的字（小票、说明书、手写），原样吐出文字和坐标，不解释、不总结、不教识字。入参必须是 asset_ref。自己不拍照。手指指的单个字不要用本步，用 reading.point_to_character",
        typical_triggers=[
            "图上写了什么",
            "识别照片里的字",
            "OCR",
            "把小票上的字读出来",
            "说明书上印的字",
        ],
        do_not_dispatch=[
            "看图理解",
            "看图问答",
            "文档总结",
            "识字教学",
            "拍照本身",
            "搜图",
            "文生图",
            "手指指的字",
            "这个字读啥",
            "这个字念什么",
            "指字认字",
        ],
    ),
    "reading.detect_finger": _ad(
        kind="action",
        role="食指检测器",
        planner_recognize="看一张已有 Image Asset，找出食指指尖位置和指向。入参 asset_ref。自己不拍照、不认字、不 OCR。用户要认手指指的字时不要单独排本步，用 reading.point_to_character",
        typical_triggers=["检测图里的食指", "指尖在哪"],
        do_not_dispatch=["拍照本身", "认字", "整页 OCR", "投屏", "无图知识问答"],
    ),
    "reading.ocr_at_finger": _ad(
        kind="action",
        role="指尖附近文字识别器",
        planner_recognize="在已有 Image Asset 上，按本步入参 finger 裁指尖附近窗口做 OCR，产出字框。入参 asset_ref + finger。不是整页 OCR（那是 image.ocr）。用户要认指向的那个字时不要单独排本步，用 reading.point_to_character",
        typical_triggers=["识别指尖附近的字"],
        do_not_dispatch=["拍照本身", "整页 OCR", "投屏", "无图知识问答", "看图理解"],
    ),
    "reading.rank_pointed": _ad(
        kind="action",
        role="指字排序器",
        planner_recognize="根据本步入参 finger 和 chars，从候选汉字里选出食指指向的那一个。入参 asset_ref + finger + chars。自己不拍照、不检测手、不做 OCR。用户要认字时不要单独排本步，用 reading.point_to_character",
        typical_triggers=["选出手指指向的字"],
        do_not_dispatch=["拍照本身", "整页 OCR", "投屏", "无图知识问答", "检测手指"],
    ),
    "reading.point_to_character": _ad(
        kind="action",
        composition="composite",
        decomposes_to=["reading.detect_finger", "reading.ocr_at_finger", "reading.rank_pointed"],
        prefer_when=POINT_TO_CHARACTER_PREFER_WHEN,
        role="指字认字器",
        planner_recognize="看一张已排好的 Image Asset，识别手指指尖指向的那一个汉字，给出该字和读音。入参 asset_ref（常为 $asset_ref）。自己不拍照；现场图要先由拍照/上传步产出 Asset。不读整页文字（那是 OCR），不投屏",
        typical_triggers=[
            "这个字读啥",
            "手指指的是什么字",
            "指的这个字怎么读",
            "这个字念什么",
            "指着这个字",
            "认一下这个字",
            "最新照片里手指指的字",
        ],
        do_not_dispatch=[
            "拍照本身",
            "投屏",
            "整页 OCR",
            "原样读图上的字",
            "无图知识问答",
            "看图理解",
            "认电视剧名",
        ],
    ),
    "chat.smalltalk": _ad(
        kind="action",
        role="闲聊问候回复器",
        planner_recognize="只接纯寒暄：早啊、你好、谢谢、再见、在吗。疑问句、你会/你可以/能不能、要办事的口令都不要用本步",
        typical_triggers=["早啊", "你好啊", "谢谢", "再见", "在吗", "早上好"],
        do_not_dispatch=[
            "知识问答",
            "算式",
            "报时",
            "看图",
            "拍照",
            "投屏",
            "控制设备",
            "能力介绍",
            "你会…吗",
            "你可以…吗",
            "能不能…",
        ],
    ),
    "capabilities.summary": _ad(
        kind="system",
        role="在线能力口语汇总器",
        planner_recognize="用口语告诉用户此刻家里能帮什么忙，或回答「你会开灯吗」「能不能控制空调」这类会不会。只介绍，不真的去开灯/开空调，答语里不要念技术编号",
        typical_triggers=[
            "你可以做什么",
            "你能干什么",
            "你会什么",
            "有哪些能力",
            "你可以控制空调吗",
            "你会开灯吗",
            "能不能控制空调",
        ],
        do_not_dispatch=[
            "知识问答",
            "执行开灯或开空调",
            "拍照",
            "逐条朗读自描述",
            "在答语里念出其它能力的编号或技术名",
        ],
    ),
    "clock.now": _ad(
        kind="input",
        role="本机时钟读取器",
        planner_recognize="读执行边本机墙上钟，回答「现在几点了」「今天几号」。一次性读取，应当排进计划。产出 now_iso 和给人听的 time_text。不要用文本问答编时刻",
        typical_triggers=["现在几点了", "几点了", "现在时间", "今天几号", "今天日期", "几月几号", "几号了"],
        do_not_dispatch=["知识问答", "计算", "看图", "编一个时刻"],
    ),
    "asset.inventory": _ad(
        kind="system",
        role="Asset 盘点查询器",
        planner_recognize="查 Brain 已登记 Asset（image/video/audio/document/url 等）：今天拍了几张、第几张照片、最新 PDF/文档、最近保存的链接。问数量用 day=today/yesterday；取第 N 条用 index；最新一份用 type=document（或目标类型：链接用 type=url）+ order=newest_first + index=1，产出 asset_ref 可交给 printer.print / web.scraper 等。不是去拍照，不是翻手机相册/本机文件系统，不是看图理解",
        typical_triggers=[
            "我今天拍了几张照片",
            "昨天拍了多少张照片",
            "最近有哪些图",
            "刚才的照片",
            "最后一张照片",
            "给我看第五张照片",
            "最新的PDF",
            "最新的文件",
            "看下最新的pdf文档",
            "把最新的PDF打印出来",
            "把最新的文件打印出来",
        ],
        do_not_dispatch=["拍照", "看图理解", "投屏", "手机系统相册", "扫本机磁盘"],
    ),
    "asset.upload": _ad(
        kind="action",
        role="Asset 上传器",
        planner_recognize="不负责按快门。把本机 inbox 的 capture 或已有 Asset 传到家里图床/云端，产出可给后续步用的 asset_ref。拍完要给人看、给视觉问、投电视，必须另排本步，入参 $capture_ref。已有 Asset 再传一份用 asset_ref",
        typical_triggers=[
            "把这张图传到云上",
            "传到家里图床",
            "上传到图片服务器",
            "把刚拍的照片传到图床",
            "拍照后上传",
        ],
        do_not_dispatch=["拍照", "投屏", "看图理解", "Google Drive", "Dropbox"],
    ),
    "vision.perceive": _ad(
        kind="action",
        role="视觉结构化感知器",
        planner_recognize="看已经有的 Image Asset，描述客厅现在什么样（人、灯、杂物）。入参 $asset_ref。自己不拍照：现场图要先拍再上传。不负责认剧名、不投屏、不开放百科问答",
        typical_triggers=["看看客厅现在怎样", "看看客厅", "现在怎样", "描述一下画面", "客厅现在什么样"],
        do_not_dispatch=["开放问答", "拍照本身", "投屏", "认电视剧名"],
    ),
    "vision.ask": _ad(
        kind="action",
        role="看图问答器",
        planner_recognize="对着已经有的 Image Asset 问具体问题：照片里有几个人、电视画面在放什么。入参带用户原问句和 $asset_ref。自己不拍照；现场/电视画面要先拍再上传再问。不读小票上的字（那是 OCR），不编无图百科答案",
        typical_triggers=[
            "照片里有几个人",
            "照片里",
            "图里有",
            "有几个人",
            "有没有人",
            "电视在放什么",
            "屏幕上是什么",
            "电视画面里是哪部剧",
            "屏幕上在放什么",
            "客厅在看什么电视",
        ],
        do_not_dispatch=["无图知识问答", "拍照本身", "OCR", "原样读图上的字"],
    ),
    "camera.capture": _ad(
        kind="input",
        role="拍照执行器",
        planner_recognize="按快门拍一张现场照（客厅、电视画面、眼前的东西），写入本机 inbox，产出 capture_ref（还不是 Asset）。允许当「给人看 / 问图上有什么 / 投电视」的前序步。本步不上传、不投屏、不能单步当最终图。下一步上传用 $capture_ref。禁止把 path 写进 plan",
        typical_triggers=["拍一张", "看看现在", "拍照", "拍张照", "拍的照片", "拍一下", "看看客厅电视画面", "拍一下电视屏幕"],
        do_not_dispatch=["上传", "传到图床", "传到云上", "单步作为最终给用户看的图", "放歌", "无拍照直接回答画面内容"],
    ),
    "camera.capture_and_upload": _ad(
        kind="action",
        composition="composite",
        decomposes_to=["camera.capture", "asset.upload"],
        prefer_when=CAPTURE_AND_UPLOAD_PREFER_WHEN,
        role="拍照并上传器",
        planner_recognize="拍一张现场照并在同一台设备上上传成 Image Asset，产出 asset_ref。拍照后还要给人看、给视觉问、投电视时优先本步，不要再拆成拍照+上传两步（capture_ref 不能跨机）。本步不负责看图理解、不投屏",
        typical_triggers=[
            "拍张照片我看一下",
            "拍张照片我看看",
            "拍的给我看",
            "拍照后上传",
            "把刚拍的照片传到图床",
        ],
        do_not_dispatch=["只上传已有图", "看图理解本身", "投屏本身", "不再拍照只传旧图"],
    ),
    "document.scan": _ad(
        kind="input",
        role="纸质文档扫描器",
        planner_recognize="用手机系统文档扫描拍纸质（小票、文件、作业），直接上传成 Image Asset。只负责扫进系统，不读字、不算金额、不总结、不投屏。读字要另排 OCR",
        typical_triggers=["扫描一下", "扫一下", "扫描一下这个小票", "扫一下文档", "扫一下作业"],
        do_not_dispatch=["OCR", "金额识别", "看图理解", "投屏", "开灯"],
    ),
    "visual.input": _ad(
        kind="input",
        role="纸质文档扫描器",
        planner_recognize="纸质扫描的兼容入口：同样用手机文档扫描把小票/文件收成 Image Asset。不读字、不算账",
        typical_triggers=["扫描一下", "扫一下这个", "扫一下小票"],
        do_not_dispatch=["OCR", "金额识别", "看图理解", "投屏"],
    ),
    "camera.take_video": _ad(
        kind="input",
        role="短视频拍摄器",
        planner_recognize="录一段现场短视频，不是拍静照、不是看图、不是投屏",
        typical_triggers=["录一段视频", "拍个小视频", "录像"],
        do_not_dispatch=["拍照", "看图", "投屏"],
    ),
    # Wire id on some edges (legacy / GoPro) — same planner contract as camera.take_video.
    "take_video": _ad(
        kind="input",
        role="短视频拍摄器",
        planner_recognize="录一段现场短视频（兼容入口），不是拍静照、不是看图、不是投屏",
        typical_triggers=["录一段视频", "拍个小视频", "录像"],
        do_not_dispatch=["拍照", "看图", "投屏"],
    ),
    "display.photo": _ad(
        kind="output",
        role="单图投屏器",
        planner_recognize="把一张已有 Image Asset 投到电视/投屏端。入参 asset_ref（常为 $asset_ref）。这是计划步，不能只用 presentation.endpoint 代替。多张轮播不要用本步",
        typical_triggers=["把这张图投到电视", "投屏", "投到电视", "丢到电视", "放到电视"],
        do_not_dispatch=["拍多图", "幻灯片", "放歌", "按厂商选 Chromecast"],
    ),
    "display.slideshow": _ad(
        kind="output",
        role="多图幻灯片投屏器",
        planner_recognize="把多张已有 Image Asset 在电视上轮播。入参 asset_refs 数组（至少一张）。单张投屏不要用本步，不要拆成多次单图投屏",
        typical_triggers=["轮播这几张照片", "电视上放幻灯片", "把这些照片轮播"],
        do_not_dispatch=["单图投屏", "拍照", "看图", "按厂商选设备"],
    ),
    "display.pdf": _ad(
        kind="output",
        role="PDF 投屏打开器",
        planner_recognize="把本步已有的 PDF/document Asset 投到电视上显示（每页渲染成图片逐页投）。入参 asset_ref（必填，type=document，常为 $asset_ref），可选 page（默认第 1 页）。用户没指定哪份 PDF 时，先排 asset.inventory 取最新 document 再接本步。本步只打开并显示，翻页用 display.pdf.page；不打印、不 OCR、不看图理解",
        typical_triggers=["把这份 PDF 投到电视", "把最新的 PDF 投屏到电视上", "PDF 上电视", "把这个文档投到电视上看"],
        do_not_dispatch=["打印", "OCR", "看图理解", "单图投屏", "幻灯片", "翻页", "下一页"],
    ),
    "display.pdf.page": _ad(
        kind="output",
        role="PDF 投屏翻页器",
        planner_recognize="电视正在投屏 PDF 时翻页：下一页（默认）/上一页/翻到第 N 页。入参 action=next/prev/goto（goto 必填 page）。不需要 asset_ref——翻的是当前投屏会话里那份 PDF。没有正在投屏的 PDF 时本步会失败，应先经 display.pdf 打开会话",
        typical_triggers=["下一页", "上一页", "翻到第 5 页", "翻页", "往后翻", "往前翻"],
        do_not_dispatch=["打开 PDF", "投屏新文档", "打印", "看图理解", "切歌", "单图投屏"],
    ),
    "display.pdf.zoom": _ad(
        kind="output",
        role="PDF 投屏缩放器",
        planner_recognize="电视正在投屏 PDF 时放大/缩小当前页画面：中心区域按档位无损重渲染再投（1.0→1.5→2→3→4 倍）。入参 action=in（默认）/out/reset。不需要 asset_ref——缩放的是当前投屏会话里那份 PDF。翻页后自动回到原图",
        typical_triggers=["电视放大", "电视缩小", "电视还原", "放大一点", "看不清，放大"],
        do_not_dispatch=["打开 PDF", "投屏新文档", "翻页", "照片放大", "打印"],
    ),
    "notify.speak": _ad(
        kind="output",
        role="语音播报器",
        planner_recognize="把用户指定的提醒/公告原文念出来，例如「五分钟后提醒萱萱关电视」「大声说该喝水了」。入参 text=要念的那句话。不要用来回读其它步骤的答案；那种情况用 presentation.type=audio，由控制面补播",
        typical_triggers=["大声念出来", "提醒我说", "一分钟后说", "提醒萱萱", "该喝水了"],
        do_not_dispatch=["知识生成", "拍照", "投图", "唤醒应答", "把答案用语音告诉我", "用语音播放结果", "念出执行结果"],
    ),
    "printer.print": _ad(
        kind="output",
        role="文档打印机",
        planner_recognize="把本步已有的 PDF/document Asset 经本机 CUPS 队列打出纸。默认黑白（ColorModel=Gray）；彩打传 color_mode=color。入参 asset_ref（必填，type=document），可选 copies、printer_name、color_mode。不配网、不切 SoftAP、不走米家云",
        typical_triggers=["打印这份 PDF", "把文档打出来", "打印一下", "打印这个文件", "彩色打印"],
        do_not_dispatch=["配网", "切 SoftAP", "扫描", "投屏", "TTS", "知识问答"],
    ),
    "file.convert": _ad(
        kind="action",
        role="文件格式转换器",
        planner_recognize=(
            "把本步已有的一张或多张 Image Asset 按顺序合并转成一个 PDF 文档 Asset。"
            "入参 asset_refs（必填，type=image 数组，顺序即页码）、to_format=pdf"
            "（可选 from_format=image）。本能力只产出 PDF，不打印、不 OCR、不识别内容"
        ),
        typical_triggers=[
            "把这几张图转成 PDF",
            "图片转 PDF",
            "合成一个 PDF",
            "把这几张照片合并成 PDF",
            "转成 PDF 文件",
            "把扫描件导成 PDF",
        ],
        do_not_dispatch=["打印", "OCR", "看图理解", "投屏", "拍照", "图片上传本身", "文字识别"],
    ),
    "pdf.rotate": _ad(
        kind="action",
        role="PDF 旋转器（横版/竖版）",
        planner_recognize=(
            "把本步已有的 PDF/document Asset 整份转成横版或竖版（先判断当前是横版还是"
            "竖版，需要旋转的页转 90°）。入参 asset_ref（必填，type=document）、"
            "orientation（必填，portrait=竖版 / landscape=横版，可写中文）。产出新的"
            "document Asset 或无需旋转时复用原 asset_ref。转完通常交给 printer.print 打印"
        ),
        typical_triggers=[
            "把这个 PDF 转成横版",
            "把这个 PDF 转成竖版",
            "横着打这份 PDF",
            "竖着打这份 PDF",
            "把 PDF 旋转成横版",
            "PDF 横竖切换",
        ],
        do_not_dispatch=["打印", "OCR", "看图理解", "扫描", "识别内容", "PDF 合成/转图片", "配网"],
    ),
    "pdf.to_images": _ad(
        kind="action",
        role="PDF 页面渲染器",
        planner_recognize=(
            "把本步已有的 PDF/document Asset 的每页（或 page_start–page_end 页范围）"
            "渲染成高清 PNG 图片并逐页登记为 image Asset，产出 asset_refs（顺序=页码），"
            "可交给 display.slideshow 轮播、逐页 OCR、vision.ask 看某页等下游。"
            "入参 asset_ref（必填，type=document），可选 page_start/page_end/dpi（默认 200）。"
            "本能力只渲染登记图片，不投屏、不 OCR、不打印；电视翻页场景用 display.pdf，"
            "不要经本能力整份预渲染"
        ),
        typical_triggers=[
            "把这个 PDF 每页转成图片",
            "PDF 转图片",
            "把这份 PDF 拆成一页一页的图",
            "把 PDF 第 3 到 5 页转成图",
        ],
        do_not_dispatch=["打印", "OCR", "看图理解", "投屏翻页", "PDF 旋转", "图片合成 PDF", "拍照"],
    ),
    "web.scraper": _ad(
        kind="action",
        role="网页抓取器（URL / url 资产 → 核心正文/整页 → PDF/文本）",
        planner_recognize=(
            "用户给一个 http(s) 网址、或引用已登记的 Brain url 资产（type=url），"
            "要求把网页抓下来存成 PDF 或文本时用本步。入参 url（必填其一，http/https）"
            "与 asset_ref（可选，type=url 的 Brain url 资产，二选一）；mode=article "
            "抓核心正文（默认，剔除广告/导航）/ page 抓忠实整页；format=pdf（默认）/ "
            "text；renderer=auto/weasyprint/chrome（仅 pdf，本机自动挑可用引擎）；"
            "page_numbers 默认 true（每页页脚加页码，page_number_style=cn 中文「第 N 页 / "
            "共 M 页」/ numeric 数字「N / M」；native_header_footer=true 改用 Chrome "
            "原生页脚）。"
            "产出登记为新 document Asset，可交给 printer.print 打印或后续流程。本步只"
            "抓网页转文档，不打印、不问答"
        ),
        typical_triggers=[
            "把这个网页存成 PDF",
            "把网址 http… 的文章转成 PDF",
            "抓取这篇文章转成 PDF",
            "把我存的链接转成 PDF",
            "把网页正文导出成文本",
            "保存这个网页",
            "网页转 PDF",
        ],
        do_not_dispatch=["打印", "OCR", "翻译", "整页截图", "下载图片", "看图理解", "投屏", "配网", "浏览网页问答"],
    ),
    "xiaodu.speak": _ad(
        kind="output",
        role="小度音箱播报器",
        planner_recognize="把指定文案经客厅小度音箱播报出来。入参 text=要念的那句话。用户明确说「用小度说/播报」时用本步，不要用 Mac 本机 notify.speak",
        typical_triggers=["用小度说", "小度播报", "客厅音箱说", "让小度念", "小度音箱播报"],
        do_not_dispatch=["Mac 本机播报", "知识问答", "放歌", "投屏", "回读上一步答案"],
    ),
    "music.recognize": _ad(
        kind="action",
        role="识曲器（听歌识曲）",
        planner_recognize="用户想听歌识曲时（打开识曲模式/这是什么歌/帮我听听），收录客厅 10~30 秒外放声音识别是哪首歌，输出一句话 answer_text（歌名）。只识别一首，命中或 30 秒超时结束。不是按歌名点播/暂停/切歌，不是读播放器正在播放的元数据",
        typical_triggers=["打开识曲模式", "这是什么歌", "帮我听一下这首歌", "听歌识曲", "识别一下现在放的歌"],
        do_not_dispatch=["按歌名点播", "暂停", "切歌", "连蓝牙", "知识问答", "读 ncm 正在播放元数据", "播放音乐"],
    ),
    "music.play": _ad(
        kind="action",
        role="音乐播放器",
        planner_recognize="按歌名/歌手/专辑开始放歌（网易云）。入参 song/artist/album。「xxx的歌」或仅歌手：连播多首（云歌单），不是单曲。不负责连蓝牙音箱，不负责暂停/切歌，不负责下载/缓存索引",
        typical_triggers=["放一首周杰伦", "播放歌曲", "放歌", "放十年", "来首邓丽君"],
        do_not_dispatch=["蓝牙连接", "TTS", "开灯", "暂停", "下一首", "下载", "缓存"],
    ),
    "music.cache": _ad(
        kind="action",
        role="音乐索引预取器",
        planner_recognize="闲时把歌名/歌手搜索结果写入本机索引，不播放、不下载音频。入参 song/artist，可选 count（1–200，默认 100）、fetch_audio（本轮忽略）。用户说「下载/缓存xxx的歌」用本步，不是 music.play",
        typical_triggers=["下载刘德华的歌", "缓存歌曲冰雨", "下载刘德华的歌50首"],
        do_not_dispatch=["开始播放", "暂停", "TTS", "蓝牙连接", "下载音频文件"],
    ),
    "music.pause": _ad(
        kind="action",
        role="暂停播放器",
        planner_recognize="暂停当前正在放的歌，不换歌、不选新歌。用户说「暂停一下」用本步，不是停止、不是下一首",
        typical_triggers=["暂停", "暂停播放", "先停一下"],
        do_not_dispatch=["选歌", "蓝牙连接", "TTS", "下一首", "停止播放"],
    ),
    "music.resume": _ad(
        kind="action",
        role="继续播放器",
        planner_recognize="从暂停处继续刚才那首，不换歌。用户说「继续放」用本步",
        typical_triggers=["继续播放", "恢复播放", "接着放"],
        do_not_dispatch=["选歌", "蓝牙连接", "TTS", "暂停", "下一首"],
    ),
    "music.stop": _ad(
        kind="action",
        role="停止播放器",
        planner_recognize="停掉当前播放（这首结束，不是暂停可继续）。用户说「关掉音乐」用本步",
        typical_triggers=["停止播放", "关掉音乐", "别放了"],
        do_not_dispatch=["选歌", "蓝牙连接", "TTS", "暂停", "下一首"],
    ),
    "music.next": _ad(
        kind="action",
        role="下一首切换器",
        planner_recognize="切到播放队列的下一首。用户说「下一首/切歌/换一首」用本步，不是按歌名点播",
        typical_triggers=["下一首", "切歌", "换一首"],
        do_not_dispatch=["选歌", "蓝牙连接", "TTS", "暂停", "上一首"],
    ),
    "music.previous": _ad(
        kind="action",
        role="上一首切换器",
        planner_recognize="切回播放队列的上一首。用户说「上一首/上一曲」用本步",
        typical_triggers=["上一首", "上一曲"],
        do_not_dispatch=["选歌", "蓝牙连接", "TTS", "暂停", "下一首"],
    ),
    "light.set": _ad(
        kind="action",
        role="灯光控制器",
        planner_recognize="开关家里的灯（客厅大灯、台灯）：开灯、关灯、调亮一点。入参 state=on/off。不是放歌、不是念一句话假装开灯",
        typical_triggers=[
            "开灯",
            "关灯",
            "亮度 50",
            "台灯",
            "开台灯",
            "关台灯",
            "客厅灯",
            "打开灯",
            "开一下灯",
            "亮一点",
            "调亮",
            "调暗",
        ],
        do_not_dispatch=["放歌", "TTS", "拍照"],
    ),
    "climate.set": _ad(
        kind="action",
        role="空调控制器",
        planner_recognize="控制绑定的空调：开/关、制冷/制热/送风、设定 16–32 度、风速、左右/上下扫风。多台时用 appliance 显示名区分客厅空调/儿童房空调。不做新风、不做除湿、不开灯",
        typical_triggers=["打开空调", "关掉空调", "制冷 26 度", "风速高", "左右扫风", "制热", "空调调到二十六度"],
        do_not_dispatch=["放歌", "TTS", "开灯", "知识问答", "新风", "除湿"],
    ),
    "aquarium.set": _ad(
        kind="action",
        role="鱼缸控制器",
        planner_recognize="控制米家鱼缸：喂鱼、开关缸/灯/水泵、调流量。问水温也走本步读状态。不开锁、不开空调",
        typical_triggers=["喂鱼", "开鱼缸灯", "关鱼缸", "鱼缸水温", "给鱼喂一口"],
        do_not_dispatch=["开锁", "开空调", "知识问答", "TTS", "投屏"],
    ),
    "lock.status": _ad(
        kind="input",
        role="门锁状态读取器",
        planner_recognize="只读门锁现在锁没锁、门开没开。不能远程开锁、不能开门。用户说「门锁开了吗」用本步",
        typical_triggers=["门锁开了吗", "门有没有锁上", "门锁状态", "门关了吗"],
        do_not_dispatch=["远程开锁", "开门", "开灯", "知识问答"],
    ),
    "voice_test.run_trial": _ad(
        kind="action",
        role="台灯语音控制实验器",
        planner_recognize="实验用：用指定音色/语速播唤醒词和「打开台灯」，再拍一张看灯亮没亮，记一轮 SUCCESS/FAIL。日常「开灯/关灯」不要用本步",
        typical_triggers=["测试台灯语音识别成功率", "测一下语音控制台灯", "跑一轮台灯语音测试"],
        do_not_dispatch=["日常开灯", "关灯", "知识问答", "投屏", "给用户看照片"],
    ),
    "phone.call": _ad(
        kind="action",
        role="电话拨打器",
        planner_recognize="按家里通讯录的姓名打电话（打给李秀平、给妈妈打电话）。不发短信、不开灯",
        typical_triggers=["打电话", "打给", "拨打", "打个电话", "给妈妈打电话"],
        do_not_dispatch=["发短信", "开灯", "拍照", "知识问答"],
    ),
    "bluetooth.connect": _ad(
        kind="action",
        role="蓝牙音箱连接器",
        planner_recognize="把 Marshall 一类蓝牙音箱连上。只负责连接，不负责选歌播放",
        typical_triggers=["连上音箱", "连接音箱", "连上马歇尔"],
        do_not_dispatch=["放歌本身", "TTS", "开灯", "断开音箱"],
    ),
    "bluetooth.disconnect": _ad(
        kind="action",
        role="蓝牙音箱断开器",
        planner_recognize="断开已连接的蓝牙音箱。只负责断开，不负责停歌或放歌",
        typical_triggers=["断开音箱", "断开蓝牙", "断开马歇尔"],
        do_not_dispatch=["放歌本身", "TTS", "开灯", "连上音箱"],
    ),
    "network.wifi.join": _ad(
        kind="action",
        role="临时 Wi-Fi 调试连接器",
        planner_recognize="调试用：把手机临时加入指定 SSID（例如 GoPro 热点）。不是连蓝牙音箱、不是拍照、不是日常上网，不要排进用户家务计划",
        typical_triggers=["连上 GoPro 热点", "加入指定 SSID"],
        do_not_dispatch=["作为计划逐步执行", "拍照本身", "放歌", "连蓝牙音箱", "开灯", "知识问答", "日常上网"],
    ),
    "network.wifi.leave": _ad(
        kind="action",
        role="临时 Wi-Fi 调试断开器",
        planner_recognize="调试用：离开临时 SSID，回到家里默认网络。不是停歌、不是断开蓝牙音箱，不要排进用户家务计划",
        typical_triggers=["离开 GoPro 热点", "回到家里默认网络"],
        do_not_dispatch=["作为计划逐步执行", "拍照本身", "放歌", "断开蓝牙音箱", "开灯", "知识问答"],
    ),
    "pronunciation.assess": _ad(
        kind="action",
        role="整段英文朗读评测器",
        planner_recognize="给定标准朗读音频和小朋友跟读音频（均为音频 AssetRef），做整段→整段英文朗读评测，给出总分、发音准确度、流利度、完整度、韵律、重点问题单词/音素及时间位置。入参 reference_audio + student_audio。自己不录音、不上传音频、不 TTS、不投屏。两段音频须由上游上传步产出 Asset 并经 context 接进本步",
        typical_triggers=[
            "评测这段跟读",
            "给这次朗读打分",
            "评估发音",
            "assess my reading",
            "pronunciation check",
            "这次读得怎么样",
        ],
        do_not_dispatch=["录音本身", "上传音频", "TTS", "投屏", "单句打分", "知识问答", "拍照"],
    ),
}


def named_appliance_overrides(
    appliance_name: str,
    *,
    generic_triggers: list[str] | None = None,
) -> dict[str, Any]:
    """Planner fields that distinguish one bound appliance from another instance.

    Named triggers come first. Generic triggers (if any) are extras after the
    named ones so two edges never advertise identical generic-only ads.
    """
    name = str(appliance_name or "").strip()
    if not name:
        return {}
    named = [
        f"打开{name}",
        f"关掉{name}",
        f"关闭{name}",
        f"开{name}",
        f"关{name}",
    ]
    extras: list[str] = []
    for trigger in generic_triggers or []:
        text = str(trigger or "").strip()
        if text and text not in named and text not in extras:
            extras.append(text)
    return {
        "role": f"{name}控制器",
        "planner_recognize": (
            f"控制「{name}」：开关、制冷/制热/送风、设定温度、风速、扫风。"
            f"仅当用户点名该设备时使用本实例，不要派给其它同 capability 的在线节点。"
        ),
        "typical_triggers": named + extras,
    }


def attach(
    capability_id: str,
    *,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    role: str | None = None,
    planner_recognize: str | None = None,
    typical_triggers: list[str] | None = None,
    do_not_dispatch: list[str] | None = None,
) -> dict[str, Any]:
    """Build a full capability dict for heartbeat / KNOWN_CAPABILITIES."""
    base = ADS.get(capability_id)
    if base is None:
        raise KeyError(f"no planner ad for capability_id={capability_id!r}")
    out = {"capability_id": capability_id, **base}
    if role is not None:
        out["role"] = str(role)
    if planner_recognize is not None:
        out["planner_recognize"] = str(planner_recognize)
    if typical_triggers is not None:
        out["typical_triggers"] = list(typical_triggers)
    if do_not_dispatch is not None:
        out["do_not_dispatch"] = list(do_not_dispatch)
    out["input_schema"] = dict(input_schema or {})
    out["output_schema"] = dict(output_schema or {})
    return out


def composition_of(capability_id: str) -> str:
    ad = ADS.get(str(capability_id or "").strip()) or {}
    c = str(ad.get("composition") or "atomic").strip().lower()
    return c if c in VALID_COMPOSITIONS else "atomic"


def decomposes_to(capability_id: str) -> list[str]:
    ad = ADS.get(str(capability_id or "").strip()) or {}
    raw = ad.get("decomposes_to") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]
