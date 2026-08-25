#!/usr/bin/env python3
"""Generate synthetic OCR test images (Chinese + English)."""
from __future__ import annotations

import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = os.path.dirname(os.path.abspath(__file__))

CN = "/System/Library/Fonts/STHeiti Light.ttc"
CN2 = "/System/Library/Fonts/Hiragino Sans GB.ttc"
EN = "/System/Library/Fonts/Helvetica.ttc"
EN_MONO = "/System/Library/Fonts/Menlo.ttc"
FELT = "/System/Library/Fonts/MarkerFelt.ttc"
ARIAL_UNI = "/Library/Fonts/Arial Unicode.ttf"


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size, index=index)
    except OSError:
        return ImageFont.truetype(ARIAL_UNI, size=size)


def save(name: str, im: Image.Image) -> None:
    path = os.path.join(OUT, name)
    im.convert("RGB").save(path, "PNG")
    print(path)


def add_noise(im: Image.Image, amount: int = 18) -> Image.Image:
    rnd = random.Random(42)
    px = im.load()
    w, h = im.size
    for _ in range(w * h // max(1, 80 - amount)):
        x, y = rnd.randint(0, w - 1), rnd.randint(0, h - 1)
        r, g, b = px[x, y][:3]
        n = rnd.randint(-amount, amount)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return im


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    # 01 printed Chinese paragraph
    im = Image.new("RGB", (900, 520), "white")
    d = ImageDraw.Draw(im)
    d.text((40, 40), "客厅灯光已经打开。", font=font(CN, 42), fill=(20, 20, 20))
    d.text((40, 120), "请把温度调到二十六度。", font=font(CN, 36), fill=(20, 20, 20))
    d.text((40, 200), "小明今天去公园玩，晚饭前回家。", font=font(CN, 32), fill=(30, 30, 30))
    d.text((40, 280), "家庭助手读字测试样本一。", font=font(CN2, 28), fill=(40, 40, 40))
    save("syn_01_zh_print.png", im)

    # 02 English print
    im = Image.new("RGB", (900, 420), "white")
    d = ImageDraw.Draw(im)
    d.text((40, 40), "Living room lights are on.", font=font(EN, 36), fill=(15, 15, 15))
    d.text((40, 110), "Set the temperature to 26C.", font=font(EN, 32), fill=(15, 15, 15))
    d.text((40, 180), "Home Agent OCR quality sample.", font=font(EN, 28), fill=(25, 25, 25))
    d.text((40, 250), "The quick brown fox jumps over the lazy dog.", font=font(EN, 22), fill=(35, 35, 35))
    save("syn_02_en_print.png", im)

    # 03 mixed
    im = Image.new("RGB", (920, 480), "white")
    d = ImageDraw.Draw(im)
    d.text((36, 36), "混合场景 Mixed Scene", font=font(CN, 40), fill=(10, 10, 10))
    d.text((36, 110), "订单号 Order ID: HA-20260823-9188", font=font(CN, 28), fill=(20, 20, 20))
    d.text((36, 170), "收件人：高磊  Address: Chaoyang, Beijing", font=font(CN, 26), fill=(20, 20, 20))
    d.text((36, 230), "Please confirm 请确认后再执行。", font=font(CN, 26), fill=(20, 20, 20))
    d.text((36, 300), "WiFi SSID: HomeAgent_5G  Password: not-a-secret", font=font(EN_MONO, 22), fill=(40, 40, 40))
    save("syn_03_mixed.png", im)

    # 04 small font UI screenshot-like
    im = Image.new("RGB", (800, 500), (18, 22, 28))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 800, 56), fill=(32, 40, 52))
    d.text((20, 14), "Home Agent 控制台", font=font(CN, 24), fill=(240, 240, 240))
    d.text((24, 80), "Intent #71  状态: succeeded", font=font(CN, 20), fill=(220, 230, 240))
    d.text((24, 120), "capability: image.ocr", font=font(EN_MONO, 18), fill=(160, 200, 160))
    d.text((24, 160), "msg: 识别完成，共 12 个文本块", font=font(CN, 18), fill=(200, 210, 220))
    d.text((24, 210), "GET /health  POST /v1/ocr", font=font(EN_MONO, 16), fill=(180, 190, 200))
    d.text((24, 260), "127.0.0.1:9188  PP-OCRv5_server", font=font(EN_MONO, 16), fill=(140, 180, 220))
    d.text((24, 320), "取消    重试    确认", font=font(CN, 22), fill=(255, 200, 80))
    save("syn_04_ui_dark.png", im)

    # 05 receipt-like
    im = Image.new("RGB", (520, 720), (250, 250, 246))
    d = ImageDraw.Draw(im)
    d.text((40, 24), "家庭便利店", font=font(CN, 34), fill=(0, 0, 0))
    d.text((40, 80), "销售小票  Receipt", font=font(CN, 22), fill=(40, 40, 40))
    d.text((40, 130), "--------------------------------", font=font(EN_MONO, 16), fill=(80, 80, 80))
    d.text((40, 160), "矿泉水 550ml     2.00", font=font(CN, 20), fill=(20, 20, 20))
    d.text((40, 200), "面包               8.50", font=font(CN, 20), fill=(20, 20, 20))
    d.text((40, 240), "牛奶 1L           12.80", font=font(CN, 20), fill=(20, 20, 20))
    d.text((40, 290), "合计 Total       23.30", font=font(CN, 22), fill=(0, 0, 0))
    d.text((40, 340), "支付方式：微信支付", font=font(CN, 18), fill=(30, 30, 30))
    d.text((40, 380), "时间：2026-08-23 21:05", font=font(CN, 18), fill=(30, 30, 30))
    d.text((40, 430), "谢谢惠顾 Thank you", font=font(CN, 18), fill=(60, 60, 60))
    d.text((40, 480), "NO. 0001288", font=font(EN_MONO, 18), fill=(20, 20, 20))
    save("syn_05_receipt.png", im)

    # 06 book paragraph
    im = Image.new("RGB", (880, 640), (252, 248, 236))
    d = ImageDraw.Draw(im)
    para = (
        "智能家居把感知、理解、规划与执行贯通。\n"
        "大脑只负责理解与规划，设备执行在边缘。\n"
        "每个能力只看本步入参，不得从前序步骤捡漏。\n"
        "A capability must fail when required inputs are missing."
    )
    d.multiline_text((48, 48), para, font=font(CN, 26), fill=(28, 24, 18), spacing=12)
    save("syn_06_book.png", im)

    # 07 sign
    im = Image.new("RGB", (720, 280), (196, 30, 30))
    d = ImageDraw.Draw(im)
    d.text((70, 40), "禁止拍照", font=font(CN, 64), fill=(255, 255, 255))
    d.text((70, 140), "NO PHOTOGRAPHY", font=font(EN, 36), fill=(255, 255, 220))
    save("syn_07_sign.png", im)

    # 08 small text dense
    im = Image.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 20), "细小印刷：请在有效期内使用，避光保存。批号 B20260823 有效期至 2028-08-23", font=font(CN, 16), fill=(50, 50, 50))
    d.text((20, 60), "Ingredients: water, sugar, citric acid, vitamin C.", font=font(EN, 14), fill=(50, 50, 50))
    d.text((20, 100), "注意：儿童须在成人监护下使用。Keep out of reach of children.", font=font(CN, 15), fill=(50, 50, 50))
    d.text((20, 150), "生产厂家：家庭助手实验室  电话：010-8888-9188", font=font(CN, 16), fill=(50, 50, 50))
    save("syn_08_smallprint.png", im)

    # 09 rotated
    base = Image.new("RGB", (640, 200), "white")
    d = ImageDraw.Draw(base)
    d.text((30, 60), "旋转十五度的中文标题", font=font(CN, 36), fill=(10, 10, 10))
    rot = base.rotate(15, expand=True, fillcolor="white")
    canvas = Image.new("RGB", (900, 420), "white")
    canvas.paste(rot, (80, 80))
    save("syn_09_rotated.png", canvas)

    # 10 noisy
    im = Image.new("RGB", (860, 300), (235, 235, 235))
    d = ImageDraw.Draw(im)
    d.text((30, 80), "噪声干扰下的识别：客厅窗帘已关闭。", font=font(CN, 30), fill=(40, 40, 40))
    d.text((30, 150), "Noisy photo of printed Chinese text.", font=font(EN, 22), fill=(50, 50, 50))
    im = add_noise(im, 28).filter(ImageFilter.GaussianBlur(0.6))
    save("syn_10_noise.png", im)

    # 11 low contrast
    im = Image.new("RGB", (820, 240), (210, 214, 218))
    d = ImageDraw.Draw(im)
    d.text((40, 80), "低对比度：请勿打扰 Do not disturb", font=font(CN, 28), fill=(170, 176, 182))
    save("syn_11_lowcontrast.png", im)

    # 12 handwriting-ish MarkerFelt
    im = Image.new("RGB", (860, 360), "white")
    d = ImageDraw.Draw(im)
    d.text((40, 50), "手写风格备忘：买牛奶和鸡蛋", font=font(FELT, 36), fill=(20, 40, 120))
    d.text((40, 140), "Call mom at 8pm tonight", font=font(FELT, 32), fill=(120, 30, 30))
    d.text((40, 230), "记得关窗 Remember to close windows", font=font(FELT, 28), fill=(20, 80, 40))
    save("syn_12_handlike.png", im)

    # 13 ticket
    im = Image.new("RGB", (700, 360), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((8, 8, 691, 351), outline=(30, 30, 30), width=3)
    d.text((30, 24), "北京地铁 乘车凭证", font=font(CN, 32), fill=(0, 0, 0))
    d.text((30, 90), "起点：国贸  终点：望京", font=font(CN, 24), fill=(20, 20, 20))
    d.text((30, 140), "日期 Date 2026-08-23  14:32", font=font(CN, 22), fill=(20, 20, 20))
    d.text((30, 190), "票价 Fare  RMB 6.00", font=font(CN, 22), fill=(20, 20, 20))
    d.text((30, 250), "单程票  Single Journey", font=font(CN, 20), fill=(80, 80, 80))
    save("syn_13_ticket.png", im)

    # 14 numbers / table
    im = Image.new("RGB", (760, 420), "white")
    d = ImageDraw.Draw(im)
    d.text((30, 24), "快递运单 Express Waybill", font=font(CN, 28), fill=(0, 0, 0))
    d.text((30, 90), "运单号：SF 1234 5678 9012", font=font(CN, 24), fill=(20, 20, 20))
    d.text((30, 140), "重量 2.4kg   件数 1", font=font(CN, 22), fill=(20, 20, 20))
    d.text((30, 190), "电话 Tel: 138-0013-8000", font=font(CN, 22), fill=(20, 20, 20))
    d.text((30, 250), "货到付款 COD  ¥128.00", font=font(CN, 24), fill=(180, 20, 20))
    save("syn_14_waybill.png", im)

    # 15 vertical-ish stacked labels
    im = Image.new("RGB", (400, 640), (20, 90, 60))
    d = ImageDraw.Draw(im)
    d.text((80, 40), "出口", font=font(CN, 72), fill=(255, 255, 255))
    d.text((70, 180), "EXIT", font=font(EN, 48), fill=(255, 230, 80))
    d.text((50, 300), "请靠右行走", font=font(CN, 28), fill=(255, 255, 255))
    d.text((40, 380), "Keep right", font=font(EN, 26), fill=(255, 255, 255))
    d.text((70, 500), "消防通道", font=font(CN, 28), fill=(255, 210, 210))
    save("syn_15_exit_sign.png", im)


if __name__ == "__main__":
    main()
