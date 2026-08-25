"""Planner-facing capability ads (structured; not 「能：/不能：」 prose).

Wire fields (heartbeat / CAPABILITY_REGISTRY):
  kind, role, planner_recognize, typical_triggers[], do_not_dispatch[]
plus input_schema / output_schema (filled by services.py).

`kind` is system placement: input | action | output | system.
`system` = Brain-side catalog / inventory (not bound to a Runtime).
`description` is not the planning contract.
"""

from __future__ import annotations

from typing import Any, Literal

Kind = Literal["input", "action", "output", "system"]
VALID_KINDS = frozenset({"input", "action", "output", "system"})


def _ad(
    *,
    kind: Kind,
    role: str,
    planner_recognize: str,
    typical_triggers: list[str],
    do_not_dispatch: list[str],
) -> dict[str, Any]:
    k = str(kind or "").strip().lower()
    if k not in VALID_KINDS:
        raise ValueError(f"invalid capability kind={kind!r}; expected input|action|output|system")
    return {
        "kind": k,
        "role": role,
        "planner_recognize": planner_recognize,
        "typical_triggers": list(typical_triggers),
        "do_not_dispatch": list(do_not_dispatch),
    }


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
        planner_recognize="读已有 Image Asset 上印着的字（小票、说明书、手写），原样吐出文字和坐标，不解释、不总结、不教识字。入参必须是 asset_ref。自己不拍照",
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
        planner_recognize="查 Brain 已经登记过的照片/视频：今天拍了几张、昨天多少张、刚才那张、第几张。问数量用 day=today/yesterday；要看第 N 张用 index。不是去拍照，不是翻手机系统相册，不是看图理解",
        typical_triggers=[
            "我今天拍了几张照片",
            "昨天拍了多少张照片",
            "最近有哪些图",
            "刚才的照片",
            "最后一张照片",
            "给我看第五张照片",
        ],
        do_not_dispatch=["拍照", "看图理解", "投屏", "手机系统相册"],
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
    "notify.speak": _ad(
        kind="output",
        role="语音播报器",
        planner_recognize="把用户指定的提醒/公告原文念出来，例如「五分钟后提醒萱萱关电视」「大声说该喝水了」。入参 text=要念的那句话。不要用来回读其它步骤的答案；那种情况用 presentation.type=audio，由控制面补播",
        typical_triggers=["大声念出来", "提醒我说", "一分钟后说", "提醒萱萱", "该喝水了"],
        do_not_dispatch=["知识生成", "拍照", "投图", "唤醒应答", "把答案用语音告诉我", "用语音播放结果", "念出执行结果"],
    ),
    "music.play": _ad(
        kind="action",
        role="音乐播放器",
        planner_recognize="按歌名/歌手/专辑开始放歌（网易云）。入参 song/artist/album。不负责连蓝牙音箱，不负责暂停/切歌",
        typical_triggers=["放一首周杰伦", "播放歌曲", "放歌", "放十年", "来首邓丽君"],
        do_not_dispatch=["蓝牙连接", "TTS", "开灯", "暂停", "下一首"],
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
