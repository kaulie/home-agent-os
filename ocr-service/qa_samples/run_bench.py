#!/usr/bin/env python3
"""POST images to OCR via SSH to cloud-server loopback :9188."""
from __future__ import annotations

import json
import os
import subprocess
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CASES: list[dict[str, str]] = [
    {
        "path": "ocr-service/qa_samples/syn_01_zh_print.png",
        "desc": "白底印刷中文四行家居指令",
        "scene": "印刷中文",
        "expect": "客厅灯光已经打开。请把温度调到二十六度。小明今天去公园玩",
    },
    {
        "path": "ocr-service/qa_samples/syn_02_en_print.png",
        "desc": "白底英文四行",
        "scene": "英文",
        "expect": "Living room lights are on. Set the temperature to 26C.",
    },
    {
        "path": "ocr-service/qa_samples/syn_03_mixed.png",
        "desc": "中英混合订单/地址/SSID",
        "scene": "混合",
        "expect": "混合场景 Mixed Scene 订单号 Order ID",
    },
    {
        "path": "ocr-service/qa_samples/syn_04_ui_dark.png",
        "desc": "深色控制台 UI 截图风",
        "scene": "截图",
        "expect": "Home Agent 控制台 Intent #71 image.ocr",
    },
    {
        "path": "ocr-service/qa_samples/syn_05_receipt.png",
        "desc": "合成销售小票",
        "scene": "小票",
        "expect": "家庭便利店 矿泉水 合计 Total 23.30",
    },
    {
        "path": "ocr-service/qa_samples/syn_06_book.png",
        "desc": "书页风中英段落",
        "scene": "印刷中文",
        "expect": "智能家居把感知、理解、规划与执行贯通",
    },
    {
        "path": "ocr-service/qa_samples/syn_07_sign.png",
        "desc": "红底禁止拍照标识",
        "scene": "混合",
        "expect": "禁止拍照 NO PHOTOGRAPHY",
    },
    {
        "path": "ocr-service/qa_samples/syn_08_smallprint.png",
        "desc": "细小印刷配料与厂家",
        "scene": "混合",
        "expect": "细小印刷 有效期 儿童 Keep out of reach",
    },
    {
        "path": "ocr-service/qa_samples/syn_09_rotated.png",
        "desc": "旋转约 15 度中文标题",
        "scene": "合成",
        "expect": "旋转十五度的中文标题",
    },
    {
        "path": "ocr-service/qa_samples/syn_10_noise.png",
        "desc": "噪声+轻微模糊中英",
        "scene": "合成",
        "expect": "噪声干扰下的识别：客厅窗帘已关闭",
    },
    {
        "path": "ocr-service/qa_samples/syn_11_lowcontrast.png",
        "desc": "低对比度请勿打扰",
        "scene": "合成",
        "expect": "低对比度：请勿打扰 Do not disturb",
    },
    {
        "path": "ocr-service/qa_samples/syn_12_handlike.png",
        "desc": "MarkerFelt 手写风格备忘",
        "scene": "混合",
        "expect": "买牛奶和鸡蛋 Call mom",
    },
    {
        "path": "ocr-service/qa_samples/syn_13_ticket.png",
        "desc": "合成地铁乘车凭证",
        "scene": "小票",
        "expect": "北京地铁 国贸 望京 票价",
    },
    {
        "path": "ocr-service/qa_samples/syn_14_waybill.png",
        "desc": "合成快递运单",
        "scene": "混合",
        "expect": "运单号 SF 1234 货到付款",
    },
    {
        "path": "ocr-service/qa_samples/syn_15_exit_sign.png",
        "desc": "绿色出口指示牌",
        "scene": "混合",
        "expect": "出口 EXIT 请靠右行走 消防通道",
    },
    {
        "path": "img-server/img/4c616807_20260823_203159_query.png",
        "desc": "客厅电视实拍：屏幕小猫+角标 AI生成",
        "scene": "印刷中文",
        "expect": "AI生成",
    },
    {
        "path": "img-server/img/5c90fca4_20260823_194844_query.png",
        "desc": "电视实拍大字「大」+ 角标",
        "scene": "印刷中文",
        "expect": "大",
    },
    {
        "path": "server/uploads/gopro/assets/f57938525c3d_scan_1787459128070.jpg",
        "desc": "自来水缴费通知单扫描/实拍",
        "scene": "小票",
        "expect": "请及时缴费 自来水缴费通知单 用户编号",
    },
    {
        "path": "mac/data/query/20260823_194844_query.png",
        "desc": "Mac query 电视「大」字照片",
        "scene": "印刷中文",
        "expect": "大",
    },
    {
        "path": "ios/LivingRoomEdge/LivingRoomEdge/Brand/home-agent-mark.png",
        "desc": "Home Agent 品牌图形标",
        "scene": "截图",
        "expect": "",
    },
]


def extra_real() -> list[dict[str, str]]:
    extras = [
        (
            "img-server/img/667a22cd_20260823_195230_query.png",
            "客厅电视实拍 query 图 195230",
            "印刷中文",
        ),
        (
            "img-server/img/6b631aa4_20260823_194944_query.png",
            "客厅电视实拍 query 图 194944",
            "印刷中文",
        ),
        (
            "img-server/img/6bb87bda_20260823_195439_query.png",
            "客厅电视实拍 query 图 195439",
            "印刷中文",
        ),
        (
            "server/uploads/gopro/assets/7245932cf0ad_photo_1787486435.jpg",
            "GoPro/相册实拍照片",
            "印刷中文",
        ),
        (
            "mac/data/voice_tests/gopro_probe/intent269.jpg",
            "voice_tests GoPro probe 实拍",
            "印刷中文",
        ),
    ]
    out = []
    for path, desc, scene in extras:
        full = os.path.join(ROOT, path)
        if os.path.isfile(full) and os.path.getsize(full) > 100:
            out.append({"path": path, "desc": desc, "scene": scene, "expect": ""})
    return out


def ocr_local(image_path: str, timeout: int = 300) -> tuple[dict, int]:
    ctype = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    with open(image_path, "rb") as f:
        data = f.read()
    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            "curl",
            "-sS",
            "-m",
            str(timeout),
            "-X",
            "POST",
            "http://127.0.0.1:9188/v1/ocr",
            "-H",
            f"Content-Type: {ctype}",
            "--data-binary",
            "@-",
        ],
        input=data,
        capture_output=True,
        timeout=timeout + 20,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:400]
        raise RuntimeError(f"curl failed rc={proc.returncode}: {err}")
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        return json.loads(raw), ms
    except json.JSONDecodeError as e:
        raise RuntimeError(f"non-json response: {raw[:300]}") from e


def preview(text: str, n: int = 80) -> str:
    t = (text or "").replace("\n", " ").replace("|", "\\|")
    return t if len(t) <= n else t[: n - 1] + "…"


def avg_conf(blocks: list) -> str:
    vals = []
    for b in blocks or []:
        c = b.get("confidence")
        if isinstance(c, (int, float)):
            vals.append(float(c))
    if not vals:
        return ""
    return f"{sum(vals) / len(vals):.3f}"


def main() -> None:
    cases = list(CASES) + extra_real()
    results = []
    for i, case in enumerate(cases, 1):
        full = os.path.join(ROOT, case["path"])
        print(f"[{i}/{len(cases)}] {case['path']}", flush=True)
        if not os.path.isfile(full):
            results.append({**case, "error": "missing file"})
            continue
        try:
            payload, ms = ocr_local(full)
        except Exception as e:
            results.append({**case, "error": str(e), "latency_ms": None})
            continue
        text = str(payload.get("text") or "")
        blocks = payload.get("blocks") or []
        results.append(
            {
                **case,
                "filename": os.path.basename(case["path"]),
                "text": text,
                "blocks": len(blocks),
                "avg_conf": avg_conf(blocks),
                "latency_ms": ms,
                "engine": payload.get("model") or payload.get("engine"),
                "error": payload.get("error"),
            }
        )
    out_path = os.path.join(os.path.dirname(__file__), "ocr_bench_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("wrote", out_path, "n=", len(results))


if __name__ == "__main__":
    main()
