"""Shared Edge wire helpers: services[] → capabilities + schemas.

Used by register/heartbeat, debug registration, and intent planning stubs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Wire capability_ids Edge clients advertise / accept.
KNOWN_CAPABILITIES: dict[str, dict[str, Any]] = {
    'music.play': {
        'kind': 'action',
        'group': 'music',
        'service_id': 'netease.music',
        'role': '音乐播放器',
        'planner_recognize': '按歌名/歌手/专辑放歌',
        'typical_triggers': ['放一首周杰伦'],
        'do_not_dispatch': ['蓝牙连接', 'TTS', '开灯'],
        'input_schema': {
            'song': {
                'type': 'string',
                'required': False,
                'description': '歌曲',
            },
            'artist': {
                'type': 'string',
                'required': False,
                'description': '歌手',
            },
            'album': {
                'type': 'string',
                'required': False,
                'description': '专辑',
            },
        },
        'output_schema': {},
    },
    'music.pause': {
        'kind': 'action',
        'group': 'music',
        'service_id': 'netease.music',
        'role': '播放控制器',
        'planner_recognize': '控制当前播放',
        'typical_triggers': ['暂停'],
        'do_not_dispatch': ['选歌', '蓝牙连接', 'TTS'],
    },
    'music.stop': {
        'kind': 'action',
        'group': 'music',
        'service_id': 'netease.music',
        'role': '播放控制器',
        'planner_recognize': '控制当前播放',
        'typical_triggers': ['停止播放'],
        'do_not_dispatch': ['选歌', '蓝牙连接', 'TTS'],
    },
    'music.next': {
        'kind': 'action',
        'group': 'music',
        'service_id': 'netease.music',
        'role': '播放控制器',
        'planner_recognize': '控制当前播放',
        'typical_triggers': ['下一首'],
        'do_not_dispatch': ['选歌', '蓝牙连接', 'TTS'],
    },
    'music.previous': {
        'kind': 'action',
        'group': 'music',
        'service_id': 'netease.music',
        'role': '播放控制器',
        'planner_recognize': '控制当前播放',
        'typical_triggers': ['上一首'],
        'do_not_dispatch': ['选歌', '蓝牙连接', 'TTS'],
    },
    'camera.capture': {
        'kind': 'input',
        'group': 'camera',
        'service_id': 'gopro.camera',
        'role': '拍照执行器',
        'planner_recognize': '拍一张现场照片并写入本机 inbox，产出 capture_ref（还不是 Asset，没有 asset_id）。要把图给用户看、上图床或上云时下一步再排上传能力，入参 $capture_ref。禁止把 path 写进 plan。',
        'typical_triggers': ['拍一张', '看看现在', '拍照'],
        'do_not_dispatch': ['上传', '传到图床', '传到云上', '作为最终给用户看的图', '看图理解', '投屏', '放歌'],
        'input_schema': {},
        'output_schema': {
            'capture_ref': {
                'type': 'string',
                'required': True,
                'description': 'CaptureRef JSON {capture_id, type, mime_type}。本机 inbox 句柄，还不是 Asset。禁止 path / photo_url / asset_id。',
            },
        },
    },
    'document.scan': {
        'kind': 'input',
        'group': 'document',
        'service_id': 'document.scanner',
        'role': '纸质文档扫描器',
        'planner_recognize': '用 iPhone 系统文档扫描采集纸质并上传为 Image Asset',
        'typical_triggers': ['扫描一下', '扫一下', '扫描一下这个小票', '扫一下文档'],
        'do_not_dispatch': ['OCR', '金额识别', '看图理解', '投屏', '开灯'],
        'input_schema': {
            'mode': {
                'type': 'string',
                'required': False,
                'description': '默认 document',
            },
        },
        'output_schema': {
            'status': {
                'type': 'string',
                'required': True,
                'description': 'completed 或 cancelled',
            },
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': 'Image AssetRef JSON。禁止 photo_url / path / 永久 URL。',
            },
        },
    },
    'visual.input': {
        'kind': 'input',
        'group': 'document',
        'service_id': 'document.scanner',
        'role': '纸质文档扫描器',
        'planner_recognize': 'document.scan 兼容别名；用 iPhone 扫描纸质并上传 Image Asset',
        'typical_triggers': ['扫描一下', '扫一下这个'],
        'do_not_dispatch': ['OCR', '金额识别', '看图理解', '投屏'],
        'input_schema': {
            'mode': {
                'type': 'string',
                'required': False,
                'description': '默认 document',
            },
        },
        'output_schema': {
            'status': {
                'type': 'string',
                'required': True,
                'description': 'completed 或 cancelled',
            },
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': 'Image AssetRef JSON。禁止 photo_url / path / 永久 URL。',
            },
        },
    },
    'take_video': {
        'kind': 'input',
        'group': 'camera',
        'service_id': 'gopro.camera',
        'role': '短视频拍摄器',
        'planner_recognize': '录一段短视频',
        'typical_triggers': ['录一段视频'],
        'do_not_dispatch': ['拍照', '看图', '投屏'],
    },
    'display.photo': {
        'kind': 'output',
        'group': 'display',
        'service_id': 'chromecast.display',
        'role': '单图投屏器',
        'planner_recognize': '把一张图投到显示端',
        'typical_triggers': ['把这张图投到电视'],
        'do_not_dispatch': ['拍多图', '幻灯片', '放歌'],
        'input_schema': {
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。',
            },
        },
        'output_schema': {},
    },
    'display.slideshow': {
        'kind': 'output',
        'group': 'display',
        'service_id': 'chromecast.display',
        'role': '多图幻灯片投屏器',
        'planner_recognize': '把多张图做成幻灯片投屏',
        'typical_triggers': ['轮播这几张照片'],
        'do_not_dispatch': ['单图投屏', '拍照', '看图'],
        'input_schema': {
            'asset_refs': {
                'type': 'string',
                'required': True,
                'description': '必填 AssetRef JSON 数组，至少一张。例 [{"asset_id":"asset_…","type":"image"}]。禁止 photo_urls / path / 永久 URL。不传则能力无效。轮播用本能力，不要拆成多个 display.photo。',
            },
            'interval_sec': {
                'type': 'number',
                'required': False,
                'description': '每张停留秒数，默认 5',
            },
            'order': {
                'type': 'string',
                'required': False,
                'description': '默认 array_asc：array_asc / array_desc / alphabet_asc / alphabet_desc / random',
            },
        },
        'output_schema': {},
    },
    'bluetooth.connect': {
        'kind': 'action',
        'group': 'speaker',
        'service_id': 'marshall.willen',
        'role': '蓝牙音箱连接器',
        'planner_recognize': '连接或断开音箱',
        'typical_triggers': ['连上音箱'],
        'do_not_dispatch': ['放歌本身', 'TTS', '开灯'],
    },
    'bluetooth.disconnect': {
        'kind': 'action',
        'group': 'speaker',
        'service_id': 'marshall.willen',
        'role': '蓝牙音箱连接器',
        'planner_recognize': '连接或断开音箱',
        'typical_triggers': ['断开音箱'],
        'do_not_dispatch': ['放歌本身', 'TTS', '开灯'],
    },
    'notify.speak': {
        'kind': 'output',
        'group': 'notify',
        'service_id': 'local.notify',
        'role': '语音播报器',
        'planner_recognize': '把文本念出来',
        'typical_triggers': ['大声念出来', '播报结果'],
        'do_not_dispatch': ['知识生成', '拍照', '投图', '唤醒应答'],
        'input_schema': {
            'text': {
                'type': 'string',
                'required': True,
                'description': '要念出的通知/提醒文案',
            },
            'lang': {
                'type': 'string',
                'required': False,
                'description': '语言提示，如 zh_CN / en_US（映射本机 TTS 音色）',
            },
            'voice': {
                'type': 'string',
                'required': False,
                'description': '可选 edge-tts 音色，如 zh-CN-YunxiNeural（男）/ zh-CN-YunyangNeural',
            },
        },
        'output_schema': {},
    },
    'vision.perceive': {
        'kind': 'action',
        'group': 'vision',
        'service_id': 'local.vision',
        'role': '视觉结构化感知器',
        'planner_recognize': '把图片理解成结构化场景描述',
        'typical_triggers': ['看看客厅现在怎样'],
        'do_not_dispatch': ['开放问答', '拍照本身', '投屏'],
        'input_schema': {
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path。常为 $asset_ref。',
            },
            'prompt': {
                'type': 'string',
                'required': False,
                'description': '可选额外分析提示',
            },
        },
        'output_schema': {
            'summary': {
                'type': 'string',
                'required': True,
                'description': '一句话画面摘要',
            },
            'people': {
                'type': 'string',
                'required': False,
                'description': '人物列表 JSON（含 id/description/count/position）',
            },
            'spatial': {
                'type': 'string',
                'required': False,
                'description': '空间布局描述',
            },
            'actions': {
                'type': 'string',
                'required': False,
                'description': '主要动作',
            },
            'posture': {
                'type': 'string',
                'required': False,
                'description': '体态/姿势',
            },
            'lighting': {
                'type': 'string',
                'required': False,
                'description': '光线 JSON（whole + region）',
            },
        },
    },
    'vision.ask': {
        'kind': 'action',
        'group': 'vision',
        'service_id': 'local.vision',
        'role': '看图问答器',
        'planner_recognize': '基于图片回答具体问题',
        'typical_triggers': ['照片里有几个人'],
        'do_not_dispatch': ['无图知识问答', '拍照本身'],
        'input_schema': {
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path。常为 $asset_ref。',
            },
            'query': {
                'type': 'string',
                'required': True,
                'description': '用户原话，如「这个字读啥」',
            },
        },
        'output_schema': {
            'answer_text': {
                'type': 'string',
                'required': True,
                'description': '针对图+问句的中文回答；不确定时直说我不知道',
            },
        },
    },
    'query.content': {
        'kind': 'action',
        'group': 'query',
        'service_id': 'local.query',
        'role': '文本知识与推理回答器',
        'planner_recognize': '回答文本问题；用户要「画一张/生成一张/来张图」时才生图（AI 文生图，不是网上搜实拍）',
        'typical_triggers': ['为什么天是蓝的', '这道应用题怎么解', '画一只猫', '生成一张示意图'],
        'do_not_dispatch': [
            '报时',
            '看图',
            '拍照',
            '投屏',
            '控制设备',
            '资产盘点',
            '你可以做什么',
            '能力介绍',
            '你会什么',
            '闲聊问候',
            '你可以控制',
            '你会开',
            '搜网上实拍图',
            '文搜图',
            '找真实照片',
            'Openverse检索',
            '必应检索',
        ],
        'input_schema': {
            'query': {
                'type': 'string',
                'required': True,
                'description': '用户原话 / prompt。出图投屏时请保留「来张图/投电视」等语义，不要只塞主题词。',
            },
            'want_image': {
                'type': 'string',
                'required': False,
                'description': 'true 时本步必须生图并产出 asset_ref。缺省则看 query 是否含来张/图片/投屏等。',
            },
            'upload_dest': {
                'type': 'string',
                'required': False,
                'description': '生图上传目标 lan（默认）| cloud',
            },
        },
        'output_schema': {
            'answer_text': {
                'type': 'string',
                'required': True,
                'description': '文字答案；不确定时直说我不知道',
            },
            'asset_ref': {
                'type': 'string',
                'required': False,
                'description': '仅生图成功时的 AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。',
            },
            'citations': {
                'type': 'string',
                'required': False,
                'description': '来源 JSON 数组；拒答时为 []',
            },
        },
    },
    'search.images': {
        'kind': 'action',
        'group': 'search',
        'service_id': 'local.search',
        'role': '互联网实拍图检索器',
        'planner_recognize': '按关键词检索互联网存量实拍图片（必应/Openverse），不是 AI 生成，也不是家里已拍相册',
        'typical_triggers': [
            '搜一张猫的照片',
            '找网上的实拍图',
            '搜索故宫的照片',
            '给我找几张风景图',
        ],
        'do_not_dispatch': [
            'AI文生图',
            '画一张',
            '生成图片',
            '知识问答',
            '拍照',
            '看本地相册',
            '投屏本身',
        ],
        'input_schema': {
            'query': {
                'type': 'string',
                'required': True,
                'description': '搜索关键词。检索网上存量实拍图，不是 AI 生图。',
            },
            'count': {
                'type': 'string',
                'required': False,
                'description': '返回张数 1–8，默认 4',
            },
            'size': {
                'type': 'string',
                'required': False,
                'description': '可选尺寸（Bing）：Small / Medium / Large / Wallpaper',
            },
            'freshness': {
                'type': 'string',
                'required': False,
                'description': '可选时效（Bing）：Day / Week / Month',
            },
            'provider': {
                'type': 'string',
                'required': False,
                'description': '搜图源 bing | openverse',
            },
            'upload_dest': {
                'type': 'string',
                'required': False,
                'description': '登记图床目标 lan（默认）| cloud',
            },
        },
        'output_schema': {
            'asset_refs': {
                'type': 'string',
                'required': True,
                'description': 'AssetRef JSON 数组，至少一张。禁止 photo_url / path / 永久 URL。',
            },
            'query_used': {
                'type': 'string',
                'required': True,
                'description': '实际搜索关键词',
            },
            'hit_count': {
                'type': 'string',
                'required': True,
                'description': '成功登记的张数',
            },
            'provider': {
                'type': 'string',
                'required': False,
                'description': '实际使用的搜图源 bing | openverse',
            },
            'sources': {
                'type': 'string',
                'required': False,
                'description': '来源页 JSON 数组 [{name, host_page, license?}]',
            },
        },
    },
    'clock.now': {
        'kind': 'input',
        'group': 'clock',
        'service_id': 'local.clock',
        'role': '本机时钟读取器',
        'planner_recognize': '读取当前时间',
        'typical_triggers': ['现在几点了', '今天几号'],
        'do_not_dispatch': ['知识问答', '计算', '看图'],
        'input_schema': {
            'timezone': {
                'type': 'string',
                'required': False,
                'description': 'IANA 时区，如 Asia/Shanghai；缺省为本机本地时区',
            },
        },
        'output_schema': {
            'now_iso': {
                'type': 'string',
                'required': True,
                'description': 'ISO-8601 时刻，含 UTC 偏移',
            },
            'time_text': {
                'type': 'string',
                'required': True,
                'description': '给人听/看的中文时刻（现在是…点…分）；时区在 now_iso，不要念 IANA 名或 UTC+08:00',
            },
        },
    },
    'math.calculate': {
        'kind': 'action',
        'group': 'math',
        'service_id': 'local.math',
        'role': '确定性算术求值器',
        'planner_recognize': '计算简单、可解析的数学表达式',
        'typical_triggers': ['1+1等于几', '根号4', '3×5'],
        'do_not_dispatch': ['应用题', '复杂数学', '单位换算', '知识问答'],
        'input_schema': {
            'expression': {
                'type': 'string',
                'required': True,
                'description': '纯算式或算术问句。应用题、方程、单位换算、百科类问题勿填本字段。',
            },
        },
        'output_schema': {
            'answer_text': {
                'type': 'string',
                'required': True,
                'description': '如「一加一等于二。」',
            },
            'result': {
                'type': 'string',
                'required': True,
                'description': '数值结果，如「2」',
            },
        },
    },
    'asset.inventory': {
        'kind': 'system',
        'group': 'asset',
        'service_id': 'system.asset',
        'role': 'Asset 盘点查询器',
        'planner_recognize': '查询 Brain 已登记 Asset 的数量或列表（按日/类型等）',
        'typical_triggers': ['我今天拍了几张照片', '昨天拍了多少张照片', '最近有哪些图'],
        'do_not_dispatch': ['拍照', '看图理解', '投屏', '手机系统相册'],
        'input_schema': {
            'type': {'type': 'string', 'required': False, 'description': 'asset 类型，如 image / video'},
            'day': {'type': 'string', 'required': False, 'description': 'today / yesterday / YYYY-MM-DD；问昨天拍了几张填 yesterday'},
            'timezone': {'type': 'string', 'required': False, 'description': 'IANA 时区，默认 Asia/Shanghai'},
            'since': {'type': 'string', 'required': False, 'description': '起始时间 ISO 或 unix'},
            'until': {'type': 'string', 'required': False, 'description': '结束时间 ISO 或 unix（不含）'},
            'producer_capability': {
                'type': 'string',
                'required': False,
                'description': '只统计该生产者产出的 Asset（可选过滤）',
            },
            'limit': {'type': 'number', 'required': False, 'description': '返回 asset_refs 上限，默认 50'},
            'include_refs': {'type': 'string', 'required': False, 'description': 'true/false，是否产出 asset_refs'},
        },
        'output_schema': {
            'count': {'type': 'string', 'required': True, 'description': '匹配数量'},
            'answer_text': {'type': 'string', 'required': True, 'description': '中文盘点结果'},
            'asset_refs': {'type': 'string', 'required': False, 'description': 'AssetRef JSON 数组'},
        },
    },
    'image.ocr': {
        'kind': 'system',
        'group': 'ocr',
        'service_id': 'system.ocr',
        'role': '图片文字识别器',
        'planner_recognize': '把图片上的文字转成带坐标的结构化 OCR 结果（原样读字，不做语义理解）',
        'typical_triggers': ['图上写了什么', '识别照片里的字', 'OCR', '把小票上的字读出来'],
        'do_not_dispatch': [
            '看图理解',
            '看图问答',
            '文档总结',
            '识字教学',
            '拍照本身',
            '搜图',
            '文生图',
        ],
        'input_schema': {
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': '图片 AssetRef JSON {asset_id, type}。禁止 image_url / path / base64。',
            },
            'language': {
                'type': 'string',
                'required': False,
                'description': 'zh（默认）或 en',
            },
        },
        'output_schema': {
            'text': {
                'type': 'string',
                'required': True,
                'description': '图上全部识别文字',
            },
            'blocks': {
                'type': 'string',
                'required': True,
                'description': 'OCR 块 JSON 数组',
            },
            'asset_id': {
                'type': 'string',
                'required': True,
                'description': '入参图片 asset_id',
            },
        },
    },
    'asset.upload': {
        'kind': 'action',
        'group': 'asset',
        'service_id': 'local.asset',
        'role': 'Asset 上传器',
        'planner_recognize': '把本机 inbox 的 capture 或已有 Asset 上传到图片服务器（本机 img-server 或云端）。拍照后要把图给用户看、上图床或上云时必须另排本步，入参带 $capture_ref。已有 Asset 再传一份时用 asset_ref。',
        'typical_triggers': [
            '把这张图传到云上',
            '传到家里图床',
            '上传到图片服务器',
            '把刚拍的照片传到图床',
            '拍照后上传',
            '把拍的给我看',
            '拍张照片我看看',
        ],
        'do_not_dispatch': ['拍照', '投屏', '看图理解', 'Google Drive', 'Dropbox'],
        'input_schema': {
            'capture_ref': {
                'type': 'string',
                'required': False,
                'description': '本机 inbox CaptureRef JSON {capture_id, type, mime_type}。拍照后上传常为 $capture_ref。',
            },
            'asset_ref': {
                'type': 'string',
                'required': False,
                'description': '已登记 Asset 的 AssetRef JSON。禁止 photo_url / path。已有 Asset 再传一份时用。',
            },
            'dest': {
                'type': 'string',
                'required': False,
                'description': 'img_server（默认）| cloud | gdrive | dropbox。gdrive/dropbox 本轮未实现。',
            },
        },
        'output_schema': {
            'asset_ref': {
                'type': 'string',
                'required': True,
                'description': '上传后的 AssetRef JSON',
            },
            'dest': {
                'type': 'string',
                'required': True,
                'description': 'img_server 或 cloud',
            },
        },
    },
    'chat.smalltalk': {
        'kind': 'action',
        'group': 'chat',
        'service_id': 'local.chat',
        'role': '闲聊问候回复器',
        'planner_recognize': '仅匹配纯寒暄短语（早啊/你好/谢谢/再见/在吗），不含疑问句、不含你会/你可以/能不能',
        'typical_triggers': ['早啊', '你好啊', '谢谢', '再见', '在吗'],
        'do_not_dispatch': [
            '知识问答',
            '算式',
            '报时',
            '看图',
            '拍照',
            '投屏',
            '控制设备',
            '能力介绍',
            '你会…吗',
            '你可以…吗',
            '能不能…',
        ],
        'input_schema': {
            'text': {'type': 'string', 'required': True, 'description': '用户的话'},
        },
        'output_schema': {
            'reply': {'type': 'string', 'required': True, 'description': '回复的话'},
        },
    },
    'capabilities.summary': {
        'kind': 'system',
        'group': 'meta',
        'service_id': 'system.capabilities',
        'role': '在线能力口语汇总器',
        'planner_recognize': '根据各能力自描述，用简短口语介绍当前能帮用户做什么，或回答会不会控制某类设备（给用户听）',
        'typical_triggers': [
            '你可以做什么',
            '你能干什么',
            '你会什么',
            '有哪些能力',
            '你可以控制空调吗',
            '你会开灯吗',
            '能不能控制空调',
        ],
        'do_not_dispatch': [
            '知识问答',
            '执行开灯或开空调',
            '拍照',
            '逐条朗读自描述',
            '在答语里念出其它能力的编号或技术名',
        ],
        'input_schema': {},
        'output_schema': {
            'answer_text': {
                'type': 'string',
                'required': True,
                'description': '给用户听的简短口语能力介绍',
            },
            'capability_count': {
                'type': 'string',
                'required': False,
                'description': '当前在线可调度能力数量',
            },
        },
    },

    'voice.stream': {
        'kind': 'input',
        'group': 'voice',
        'service_id': 'local.voice',
        'role': '常驻语音流入口',
        'planner_recognize': '按自身策略收音并转写，将用户口语变成系统意图',
        'typical_triggers': ['对着麦克风说话', '语音下指令'],
        'do_not_dispatch': ['作为计划逐步执行', '知识问答', '控制设备', '投屏'],
        'input_schema': {},
        'output_schema': {
            'transcript': {
                'type': 'string',
                'required': False,
                'description': '最近一次转写（观测用；常驻入口不经计划逐步产出）',
            },
        },
    },

    'voicewakeup.echo': {
        'kind': 'output',
        'group': 'voice',
        'service_id': 'local.voice',
        'role': '唤醒回声',
        'planner_recognize': '唤醒应答由语音入口本机完成，不要排进用户任务计划',
        'typical_triggers': ['系统内部唤醒回声（非用户指令）'],
        'do_not_dispatch': [
            '作为计划逐步执行',
            '普通播报',
            '提醒',
            '念答案',
            '知识问答',
            '控制设备',
            '报时',
        ],
        'input_schema': {
            'text': {
                'type': 'string',
                'required': False,
                'description': '回声文案；缺省为又咋了',
            },
        },
        'output_schema': {
            'echo_text': {
                'type': 'string',
                'required': True,
                'description': '实际念出的文案',
            },
        },
    },

    'video.live_stream': {
        'kind': 'input',
        'group': 'video',
        'service_id': 'iphone.video',
        'role': 'iPhone 实时视频流入口',
        'planner_recognize': '把 iPhone 摄像头编成实时视频流推到 Mac Edge',
        'typical_triggers': ['开始直播', '推摄像头画面'],
        'do_not_dispatch': ['作为计划逐步执行', '看图理解', '抽帧上传', '投屏'],
        'input_schema': {},
        'output_schema': {
            'stream_id': {
                'type': 'string',
                'required': False,
                'description': '本次推流 id（观测用；常驻入口不经计划逐步产出）',
            },
        },
    },

    'light.set': {
        'kind': 'action',
        'group': 'light',
        'service_id': 'livingroom.ceiling_light',
        'role': '灯光控制器',
        'planner_recognize': '开关灯 / 调亮度',
        'typical_triggers': ['开灯', '关灯', '亮度 50'],
        'do_not_dispatch': ['放歌', 'TTS', '拍照'],
        'input_schema': {
            'state': {
                'type': 'string',
                'required': True,
                'description': '客厅大路灯：on 开 / off 关（兼容 开、关、开灯、关灯）。禁止拆成 notify.speak。缺 state 则本能力无效。',
            },
        },
        'output_schema': {
            'state': {
                'type': 'string',
                'required': True,
                'description': '规范化后的 on 或 off',
            },
        },
    },
    'voice_test.run_trial': {
        'kind': 'action',
        'group': 'experiment',
        'service_id': 'local.voice_test',
        'role': '台灯语音控制实验器',
        'planner_recognize': '用可配置语音参数播唤醒词和开灯命令，再用摄像头判断台灯是否亮起，记录单次实验结果',
        'typical_triggers': ['测试台灯语音识别成功率', '测一下语音控制台灯', '跑一轮台灯语音测试'],
        'do_not_dispatch': ['日常开灯', '关灯', '知识问答', '投屏', '给用户看照片'],
        'input_schema': {
            'voice': {
                'type': 'string',
                'required': False,
                'description': 'TTS 音色，如 Tingting；缺省读 VoiceProfile',
            },
            'speed': {
                'type': 'number',
                'required': False,
                'description': '语速倍率，1.0 为默认',
            },
            'volume': {
                'type': 'number',
                'required': False,
                'description': '播放音量 0.0–1.0',
            },
            'command': {
                'type': 'string',
                'required': False,
                'description': '命令文案，默认 打开台灯。日常开灯不要用本能力。',
            },
            'experiment_id': {
                'type': 'string',
                'required': False,
                'description': '实验批次 id',
            },
        },
        'output_schema': {
            'result': {
                'type': 'string',
                'required': True,
                'description': 'SUCCESS / FAIL / INVALID。SUCCESS 仅当摄像头验证台灯已亮。',
            },
            'answer_text': {
                'type': 'string',
                'required': True,
                'description': '人类可读试验摘要',
            },
            'asset_ref': {
                'type': 'string',
                'required': False,
                'description': '验证图 AssetRef JSON。禁止 photo_url / path。',
            },
        },
    },
    'climate.set': {
        'kind': 'action',
        'group': 'climate',
        'service_id': 'livingroom.climate',
        'role': '空调控制器',
        'planner_recognize': '开关空调、制冷/制热/送风、设定温度、风速、扫风',
        'typical_triggers': ['打开空调', '关掉空调', '制冷 26 度', '风速高', '左右扫风'],
        'do_not_dispatch': ['放歌', 'TTS', '开灯', '知识问答', '新风', '除湿'],
        'input_schema': {
            'power': {
                'type': 'string',
                'required': False,
                'description': 'on 开 / off 关（兼容 开、关、打开、关闭）。与 mode、target_temp、fan、swing 至少填一项。off 时不可同时设模式、温度、风速或扫风。',
            },
            'mode': {
                'type': 'string',
                'required': False,
                'description': 'cool 制冷 / heat 制热 / fan 送风（兼容 制冷、制热、送风）。未写 power 时本步内部先开机。',
            },
            'target_temp': {
                'type': 'number',
                'required': False,
                'description': '设定温度，摄氏整数 16–32。送风模式不可设温。未写 power 时本步内部先开机。',
            },
            'fan': {
                'type': 'string',
                'required': False,
                'description': 'auto 自动 / diffuse 柔风 / low 低 / medium 中 / high 高（兼容 自动、柔风、低、中、高）。未写 power 时本步内部先开机。',
            },
            'swing': {
                'type': 'string',
                'required': False,
                'description': 'off 关 / on 开 / horizontal 左右 / vertical 上下（兼容 关、开、左右扫风、上下扫风）。未写 power 时本步内部先开机。',
            },
            'appliance': {
                'type': 'string',
                'required': False,
                'description': '绑定空调的显示名，如 客厅空调、儿童房空调。同一 Runtime 绑定多台时必填。',
            },
        },
        'output_schema': {
            'power': {
                'type': 'string',
                'required': True,
                'description': '规范化后的 on 或 off',
            },
            'mode': {
                'type': 'string',
                'required': True,
                'description': 'cool / heat / fan / dry / auto',
            },
            'status_text': {
                'type': 'string',
                'required': True,
                'description': '人类可读状态，如「空调已开，制冷 26°C，风速中，左右扫风」',
            },
            'target_temp': {
                'type': 'number',
                'required': False,
                'description': '当前设定温度',
            },
            'indoor_temp': {
                'type': 'number',
                'required': False,
                'description': '室内温度',
            },
            'fan': {
                'type': 'string',
                'required': False,
                'description': 'auto / diffuse / low / medium / high',
            },
            'swing': {
                'type': 'string',
                'required': False,
                'description': 'off / on / horizontal / vertical',
            },
        },
    },
    'aquarium.set': {
        'kind': 'action',
        'group': 'aquarium',
        'service_id': 'livingroom.aquarium',
        'role': '鱼缸控制器',
        'planner_recognize': '开关米家鱼缸、灯光、水泵，调节流量，远程喂食',
        'typical_triggers': ['喂鱼', '开鱼缸灯', '关鱼缸', '鱼缸水温'],
        'do_not_dispatch': ['开锁', '开空调', '知识问答', 'TTS', '投屏'],
        'input_schema': {
            'power': {
                'type': 'string',
                'required': False,
                'description': 'on 开 / off 关。与 light、pump、pump_flux、feed 至少填一项。',
            },
            'light': {
                'type': 'string',
                'required': False,
                'description': 'on 开灯 / off 关灯',
            },
            'pump': {
                'type': 'string',
                'required': False,
                'description': 'on 开水泵 / off 关水泵',
            },
            'pump_flux': {
                'type': 'number',
                'required': False,
                'description': '水泵流量 1–10',
            },
            'feed': {
                'type': 'string',
                'required': False,
                'description': 'true 或 1–10：立即喂一份/指定份数。禁止从前序 step 补。',
            },
        },
        'output_schema': {
            'status_text': {
                'type': 'string',
                'required': True,
                'description': '人类可读状态，如「鱼缸已开，灯开，水温26°C」',
            },
            'power': {
                'type': 'string',
                'required': False,
                'description': 'on / off',
            },
            'light': {
                'type': 'string',
                'required': False,
                'description': 'on / off',
            },
            'pump': {
                'type': 'string',
                'required': False,
                'description': 'on / off',
            },
            'pump_flux': {
                'type': 'number',
                'required': False,
                'description': '当前水泵流量',
            },
            'water_temp': {
                'type': 'number',
                'required': False,
                'description': '水温摄氏',
            },
            'fed': {
                'type': 'boolean',
                'required': False,
                'description': '本步是否已喂食',
            },
        },
    },
    'lock.status': {
        'kind': 'input',
        'group': 'lock',
        'service_id': 'entry.lock',
        'role': '门锁状态读取器',
        'planner_recognize': '读取门锁是否上锁、门是否开着；不能远程开锁',
        'typical_triggers': ['门锁开了吗', '门有没有锁上', '门锁状态'],
        'do_not_dispatch': ['远程开锁', '开门', '开灯', '知识问答'],
        'input_schema': {},
        'output_schema': {
            'status_text': {
                'type': 'string',
                'required': True,
                'description': '人类可读状态，如「已上锁，门关着」',
            },
            'locked': {
                'type': 'string',
                'required': False,
                'description': 'locked / unlocked',
            },
            'door': {
                'type': 'string',
                'required': False,
                'description': 'closed / open / ajar / unknown',
            },
            'online': {
                'type': 'boolean',
                'required': True,
                'description': '门锁云端是否在线',
            },
        },
    },
}

try:
    from capability_ads import ADS as _PLANNER_ADS
except ImportError:  # pragma: no cover
    from server.capability_ads import ADS as _PLANNER_ADS  # type: ignore

for _cid, _spec in KNOWN_CAPABILITIES.items():
    _ad = _PLANNER_ADS.get(_cid)
    if not isinstance(_ad, dict):
        continue
    if _ad.get("kind"):
        _spec["kind"] = _ad["kind"]
    if _ad.get("role"):
        _spec["role"] = _ad["role"]
    if _ad.get("planner_recognize"):
        _spec["planner_recognize"] = _ad["planner_recognize"]
    if _ad.get("typical_triggers"):
        _spec["typical_triggers"] = list(_ad["typical_triggers"])
    if _ad.get("do_not_dispatch"):
        _spec["do_not_dispatch"] = list(_ad["do_not_dispatch"])


LEGACY_CAPABILITIES = frozenset(
    {
        "music.playback",
        "music.search",
        "take_photo",
        "bluetooth.a2dp",
        "gopro.capture",
        "gopro.shutter",
        "endpoint.feedback",
        "endpoint.present",
    }
)


def _as_schema_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for name, field in value.items():
        key = str(name).strip()
        if not key:
            continue
        if isinstance(field, dict):
            entry: dict[str, Any] = {
                "type": str(field.get("type") or "string"),
                "description": str(field.get("description") or ""),
            }
            if "required" in field:
                entry["required"] = bool(field.get("required"))
            out[key] = entry
        else:
            out[key] = {"type": "string", "required": False, "description": ""}
    return out


def _as_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip()
        if s:
            out.append(s)
    return out


def normalize_capability(raw: Any) -> dict[str, Any] | None:
    """Normalize one capability descriptor; return None if invalid.

    Planner contract fields: role, planner_recognize, typical_triggers, do_not_dispatch.
    `description` is optional / non-authoritative (legacy edges may still send it).
    """
    if not isinstance(raw, dict):
        return None
    cap_id = str(
        raw.get("capability_id") or raw.get("capabilityId") or raw.get("id") or ""
    ).strip()
    if not cap_id:
        return None
    role = str(raw.get("role") or "").strip()
    planner_recognize = str(
        raw.get("planner_recognize") or raw.get("plannerRecognize") or ""
    ).strip()
    typical = _as_string_list(
        raw.get("typical_triggers")
        if "typical_triggers" in raw
        else raw.get("typicalTriggers")
    )
    do_not = _as_string_list(
        raw.get("do_not_dispatch")
        if "do_not_dispatch" in raw
        else raw.get("doNotDispatch")
    )
    # Legacy prose description: keep for display only; do not invent from structured fields.
    description = str(raw.get("description") or "").strip()
    return {
        "capability_id": cap_id,
        "role": role,
        "planner_recognize": planner_recognize,
        "typical_triggers": typical,
        "do_not_dispatch": do_not,
        "description": description,
        "input_schema": _as_schema_object(
            raw.get("input_schema") if "input_schema" in raw else raw.get("inputSchema")
        ),
        "output_schema": _as_schema_object(
            raw.get("output_schema") if "output_schema" in raw else raw.get("outputSchema")
        ),
    }


def normalize_service(raw: Any) -> dict[str, Any] | None:
    """Normalize one service descriptor; return None if invalid."""
    if not isinstance(raw, dict):
        return None
    service_id = str(
        raw.get("service_id") or raw.get("serviceId") or raw.get("id") or ""
    ).strip()
    group = str(raw.get("group") or "").strip()
    if not service_id or not group:
        return None
    caps_raw = raw.get("capabilities")
    caps: list[dict[str, Any]] = []
    if isinstance(caps_raw, list):
        for item in caps_raw:
            cap = normalize_capability(item)
            if cap is not None:
                caps.append(cap)
    return {
        "service_id": service_id,
        "display_name": str(
            raw.get("display_name") or raw.get("displayName") or service_id
        ).strip(),
        "version": str(raw.get("version") or "").strip() or "0.0.0",
        "group": group,
        "capabilities": caps,
    }


def normalize_services(raw: Any) -> list[dict[str, Any]]:
    """Parse body.services into canonical list (drops invalid entries)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        svc = normalize_service(item)
        if svc is None:
            continue
        sid = svc["service_id"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(svc)
    return out


def strip_legacy_edge_fields(info: dict[str, Any]) -> dict[str, Any]:
    """Destructive: remove top-level skills / flat capabilities from edge snapshot."""
    info.pop("skills", None)
    info.pop("capabilities", None)
    return info


def validate_services(services: list[dict[str, Any]]) -> list[str]:
    """Return human-readable validation errors (empty = ok). Empty services is allowed."""
    errors: list[str] = []
    for i, svc in enumerate(services):
        if not svc.get("service_id"):
            errors.append(f"services[{i}].service_id required")
        if not svc.get("group"):
            errors.append(f"services[{i}].group required")
        caps = svc.get("capabilities")
        if not isinstance(caps, list):
            errors.append(f"services[{i}].capabilities must be a list")
            continue
        for j, cap in enumerate(caps):
            if not isinstance(cap, dict) or not cap.get("capability_id"):
                errors.append(f"services[{i}].capabilities[{j}].capability_id required")
                continue
            if not isinstance(cap.get("input_schema"), dict):
                errors.append(f"services[{i}].capabilities[{j}].input_schema must be object")
            if not isinstance(cap.get("output_schema"), dict):
                errors.append(f"services[{i}].capabilities[{j}].output_schema must be object")
    return errors


def index_capabilities_from_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build online capability index from edge heartbeats:
    [{ edge_id, service_id, group, capability_id, role, planner_recognize,
       typical_triggers, do_not_dispatch, description?, input_schema, output_schema }]
    """
    rows: list[dict[str, Any]] = []
    for edge in edges:
        edge_id = str(edge.get("edge_id") or edge.get("edgeId") or "").strip()
        services = edge.get("services")
        if not isinstance(services, list):
            continue
        for svc in services:
            if not isinstance(svc, dict):
                continue
            service_id = str(svc.get("service_id") or "").strip()
            group = str(svc.get("group") or "").strip()
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict):
                    continue
                norm = normalize_capability(cap)
                if norm is None:
                    continue
                rows.append(
                    {
                        "edge_id": edge_id,
                        "service_id": service_id,
                        "group": group,
                        "capability_id": norm["capability_id"],
                        "role": norm.get("role") or "",
                        "planner_recognize": norm.get("planner_recognize") or "",
                        "typical_triggers": list(norm.get("typical_triggers") or []),
                        "do_not_dispatch": list(norm.get("do_not_dispatch") or []),
                        "description": norm.get("description") or "",
                        "input_schema": norm.get("input_schema") or {},
                        "output_schema": norm.get("output_schema") or {},
                        "online_status": edge.get("online_status") or edge.get("onlineStatus"),
                    }
                )
    return rows


def find_edges_for_capability(
    edges: list[dict[str, Any]],
    capability_id: str,
    *,
    online_only: bool = True,
) -> list[dict[str, Any]]:
    """Edges that advertise capability_id (optionally online only)."""
    want = (capability_id or "").strip()
    if not want:
        return []
    out: list[dict[str, Any]] = []
    for edge in edges:
        status = str(edge.get("online_status") or edge.get("onlineStatus") or "").lower()
        if online_only and status != "online":
            continue
        for row in index_capabilities_from_edges([edge]):
            if row["capability_id"] == want:
                out.append(deepcopy(edge))
                break
    return out


def edge_capability_ids(edge: dict[str, Any]) -> set[str]:
    """Set of capability_id advertised on one edge snapshot."""
    return {
        str(row["capability_id"])
        for row in index_capabilities_from_edges([edge])
        if row.get("capability_id")
    }


def plan_required_capabilities(plan: list[dict[str, Any]]) -> list[str]:
    """Ordered unique capability ids from an execution_plan."""
    seen: set[str] = set()
    out: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        cap = str(step.get("capability") or "").strip()
        if not cap or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def resolve_edge_for_plan(
    plan: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    preferred_edge_id: str | None = None,
    room: str | None = None,
    online_only: bool = True,
) -> dict[str, Any]:
    """
    Pick a single online edge that covers all capabilities in the plan.

    Returns:
      { ok, edge_id?, reason, required_capabilities, candidates[] }
    """
    required = plan_required_capabilities(plan)
    if not required:
        return {
            "ok": False,
            "edge_id": None,
            "reason": "execution_plan has no capabilities",
            "required_capabilities": [],
            "candidates": [],
        }

    preferred = (preferred_edge_id or "").strip()
    want_room = (room or "").strip()
    candidates: list[dict[str, Any]] = []
    skipped_skew: list[str] = []
    for edge in edges:
        status = str(edge.get("online_status") or edge.get("onlineStatus") or "").lower()
        if online_only and status != "online":
            continue
        edge_id = str(edge.get("edge_id") or edge.get("edgeId") or "").strip()
        if not edge_id:
            continue
        # Clock skew: Brain refuses to schedule onto ineligible nodes.
        if edge.get("schedule_eligible") is False:
            skipped_skew.append(edge_id)
            continue
        caps = edge_capability_ids(edge)
        if not set(required).issubset(caps):
            continue
        candidates.append(deepcopy(edge))

    if not candidates:
        reason = f"no online edge for capabilities: {', '.join(required)}"
        if skipped_skew:
            reason += f"; clock-skew rejected: {', '.join(skipped_skew)}"
        return {
            "ok": False,
            "edge_id": None,
            "reason": reason,
            "required_capabilities": required,
            "candidates": [],
            "clock_skew_rejected": skipped_skew,
        }

    def sort_key(edge: dict[str, Any]) -> tuple[int, int, str]:
        eid = str(edge.get("edge_id") or "").strip()
        pref_rank = 0 if preferred and eid == preferred else 1
        edge_room = str(edge.get("room") or "").strip()
        room_rank = 0 if want_room and edge_room == want_room else 1
        return (pref_rank, room_rank, eid)

    candidates.sort(key=sort_key)
    if len(candidates) > 1 and not preferred:
        labels = []
        seen = set()
        for edge in candidates:
            eid = str(edge.get("edge_id") or "").strip()
            name = str(edge.get("display_name") or eid).strip() or eid
            if name not in seen:
                seen.add(name)
                labels.append(name)
        listed = "、".join(labels)
        return {
            "ok": False,
            "edge_id": None,
            "reason": (
                "有多台在线设备都能执行该能力，且计划未指定要用哪一台。"
                f"请说清楚设备名称后再试。候选：{listed}。"
            ),
            "required_capabilities": required,
            "candidates": [str(c.get("edge_id") or "") for c in candidates],
        }
    chosen = candidates[0]
    chosen_id = str(chosen.get("edge_id") or "").strip()
    reason_parts = [f"matched {', '.join(required)}"]
    if preferred and chosen_id == preferred:
        reason_parts.append("preferred_edge_id")
    elif want_room and str(chosen.get("room") or "").strip() == want_room:
        reason_parts.append(f"room={want_room}")
    return {
        "ok": True,
        "edge_id": chosen_id,
        "reason": "; ".join(reason_parts),
        "required_capabilities": required,
        "candidates": [str(c.get("edge_id") or "") for c in candidates],
    }


def plan_assigned_edge_ids(plan: Any) -> list[str]:
    """Distinct non-empty per-step assigned_edge_id values, in first-seen order."""
    if not isinstance(plan, list):
        return []
    seen: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        eid = str(
            step.get("assigned_edge_id") or step.get("assignedEdgeId") or ""
        ).strip()
        if eid and eid not in seen:
            seen.append(eid)
    return seen


def assign_steps_to_edges(
    plan: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    preferred_edge_id: str | None = None,
    room: str | None = None,
) -> list[dict[str, Any]]:
    """Assign each step to an online edge that covers that step's capability."""
    if not plan:
        raise ValueError("execution_plan has no steps")
    assigned_steps: list[dict[str, Any]] = []
    reasons: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        step_copy = dict(step)
        existing = str(step_copy.get("assigned_edge_id") or "").strip()
        routed = resolve_edge_for_plan(
            [step_copy],
            edges,
            preferred_edge_id=existing or preferred_edge_id,
            room=room,
            online_only=True,
        )
        if not routed.get("ok") or not routed.get("edge_id"):
            cap = str(step_copy.get("capability") or "?")
            raise ValueError(
                str(routed.get("reason") or f"no online edge for step capability {cap}")
            )
        eid = str(routed["edge_id"]).strip()
        step_copy["assigned_edge_id"] = eid
        step_copy.pop("assignedEdgeId", None)
        assigned_steps.append(step_copy)
        reasons.append(
            f"step{step_copy.get('step')}:{step_copy.get('capability')}→{eid}"
        )
    return assigned_steps


def resolve_tts_edge_id(edges: list[dict[str, Any]]) -> str | None:
    """Pick the designated Edge for voice TTS delivery (notify.speak)."""
    import os

    explicit = os.environ.get("PRESENTATION_TTS_EDGE_ID", "").strip()
    online = [
        e
        for e in edges
        if str(e.get("online_status") or e.get("onlineStatus") or "").lower() == "online"
        and e.get("schedule_eligible") is not False
    ]

    def has_speak(edge: dict[str, Any]) -> bool:
        return "notify.speak" in edge_capability_ids(edge)

    if explicit:
        for edge in online:
            if str(edge.get("edge_id") or edge.get("edgeId") or "").strip() == explicit:
                return explicit if has_speak(edge) else None
        return None

    laptop_candidates: list[dict[str, Any]] = []
    for edge in online:
        if not has_speak(edge):
            continue
        hint = str(
            edge.get("role")
            or edge.get("client_hint")
            or edge.get("clientHint")
            or ""
        ).lower()
        if "laptop" in hint or hint == "living-room-mac":
            laptop_candidates.append(edge)
    if laptop_candidates:
        return str(laptop_candidates[0].get("edge_id") or "").strip() or None
    for edge in online:
        if has_speak(edge):
            return str(edge.get("edge_id") or "").strip() or None
    return None


def normalize_execution_plan(plan: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Normalize execution_plan steps.
    Returns (plan, error). Rejects legacy capability ids.
    Extra step fields (song/artist/…) are preserved as params on the step.
    """
    if plan is None:
        return [], None
    if not isinstance(plan, list):
        return None, "execution_plan must be a list"
    out: list[dict[str, Any]] = []
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            return None, f"execution_plan[{i}] must be an object"
        cap = str(step.get("capability") or "").strip()
        if not cap:
            return None, f"execution_plan[{i}].capability required"
        if cap in LEGACY_CAPABILITIES:
            return None, (
                f"execution_plan[{i}].capability '{cap}' is legacy; "
                f"use new ids (e.g. music.play, camera.capture)"
            )
        normalized = dict(step)
        normalized["capability"] = cap
        if "step" not in normalized:
            normalized["step"] = i + 1
        # execution_timing: strip delay_sec; normalize absolute ms fields.
        try:
            from execution_timing import normalize_execution_timing_dict
        except ImportError:  # pragma: no cover
            from server.execution_timing import normalize_execution_timing_dict  # type: ignore
        normalized.pop("delay_sec", None)
        if "execution_timing" in normalized:
            timing = normalize_execution_timing_dict(normalized.get("execution_timing"))
            if timing is None:
                normalized.pop("execution_timing", None)
            else:
                normalized["execution_timing"] = timing
        # Wire schema field names for music.play: song / artist / album only.
        if cap == "music.play":
            if "author" in normalized and "artist" not in normalized:
                normalized["artist"] = normalized.pop("author")
            else:
                normalized.pop("author", None)
            if "singer_name" in normalized and "artist" not in normalized:
                normalized["artist"] = normalized.pop("singer_name")
            else:
                normalized.pop("singer_name", None)
            if "song_name" in normalized and "song" not in normalized:
                normalized["song"] = normalized.pop("song_name")
            else:
                normalized.pop("song_name", None)
            if "song" in normalized and normalized["song"] is not None:
                normalized["song"] = str(normalized["song"]).strip()
            if "artist" in normalized and normalized["artist"] is not None:
                artist = str(normalized["artist"]).strip()
                if artist:
                    normalized["artist"] = artist
                else:
                    normalized.pop("artist", None)
            if "album" in normalized and normalized["album"] is not None:
                album = str(normalized["album"]).strip()
                if album:
                    normalized["album"] = album
                else:
                    normalized.pop("album", None)
        out.append(normalized)
    return out, None


def plan_music_play(*, song: str, artist: str | None = None, step: int = 1) -> list[dict[str, Any]]:
    item: dict[str, Any] = {"capability": "music.play", "step": step, "song": song.strip()}
    if artist and artist.strip():
        item["artist"] = artist.strip()
    return [item]


def plan_camera_capture(*, step: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "capability": "camera.capture",
            "step": step,
            "input_constrict": {},
            "output_constrict": {
                "capture_ref": {"type": "string", "data_dest": "context"}
            },
        }
    ]


def plan_asset_upload(*, capture_ref: str = "$capture_ref", dest: str = "img_server", step: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "capability": "asset.upload",
            "step": step,
            "input_constrict": {
                "capture_ref": (capture_ref or "").strip() or "$capture_ref",
                "dest": (dest or "").strip() or "img_server",
            },
            "output_constrict": {
                "asset_ref": {"type": "string", "data_dest": "context"},
                "dest": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_take_video(*, step: int = 1) -> list[dict[str, Any]]:
    return [{"capability": "take_video", "step": step}]


def plan_notify_speak(
    *,
    text: str,
    lang: str | None = None,
    step: int = 1,
) -> list[dict[str, Any]]:
    """Mac local TTS notification (notify.speak)."""
    item: dict[str, Any] = {
        "capability": "notify.speak",
        "step": step,
        "input_constrict": {"text": (text or "").strip() or "提醒"},
    }
    if lang and str(lang).strip():
        item["input_constrict"]["lang"] = str(lang).strip()
    return [item]


def plan_vision_perceive(
    *,
    photo_url: str = "$photo_url",
    prompt: str | None = None,
    step: int = 1,
) -> list[dict[str, Any]]:
    """photo_url in → flat summary/people/… out (helper for tests/docs only).

    Brain does not rewrite vision output_constrict — planner/Edge own the keys.
    """
    flat = {
        k: {"type": "string", "data_dest": "context"}
        for k in (
            "summary",
            "people",
            "spatial",
            "actions",
            "posture",
            "lighting",
        )
    }
    item: dict[str, Any] = {
        "capability": "vision.perceive",
        "step": step,
        "input_constrict": {"photo_url": (photo_url or "").strip() or "$photo_url"},
        "output_constrict": flat,
    }
    if prompt and str(prompt).strip():
        item["input_constrict"]["prompt"] = str(prompt).strip()
    return [item]


def plan_vision_ask(
    *,
    photo_url: str = "$photo_url",
    query: str,
    step: int = 1,
) -> list[dict[str, Any]]:
    """photo_url + query in → answer_text (helper for tests/docs only)."""
    return [
        {
            "capability": "vision.ask",
            "step": step,
            "input_constrict": {
                "photo_url": (photo_url or "").strip() or "$photo_url",
                "query": (query or "").strip(),
            },
            "output_constrict": {
                "answer_text": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_query_content(
    *,
    query: str,
    step: int = 1,
) -> list[dict[str, Any]]:
    """query in → answer_text / optional photo_url / citations (helper for tests/docs)."""
    return [
        {
            "capability": "query.content",
            "step": step,
            "input_constrict": {"query": (query or "").strip()},
            "output_constrict": {
                "answer_text": {"type": "string", "data_dest": "context"},
                "photo_url": {"type": "string", "data_dest": "context"},
                "citations": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_clock_now(*, step: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "capability": "clock.now",
            "step": step,
            "input_constrict": {},
            "output_constrict": {
                "now_iso": {"type": "string", "data_dest": "context"},
                "time_text": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_display_photo(*, photo_url: str = "$photo_url", step: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "capability": "display.photo",
            "step": step,
            "input_constrict": {"photo_url": (photo_url or "").strip() or "$photo_url"},
        }
    ]


def plan_music_control(*, capability: str, step: int = 1) -> list[dict[str, Any]]:
    cap = (capability or "").strip()
    return [{"capability": cap, "step": step}]
