import Foundation
import UIKit

/// Identity plus optional Runtime (GoPro / light / Hisense climate).
enum ParticipantStore {
    private static let hintKey = "livingroom.clientHint"
    private static let idKey = "livingroom.participantId"
    private static let brainKey = "livingroom.registeredBrainURL"
    private static let registeredAtKey = "livingroom.registeredAt"
    private static let lastHeartbeatAtKey = "livingroom.lastHeartbeatAt"
    private static let rolesKey = "livingroom.enabledRoles"
    private static let lastReportedRolesKey = "livingroom.lastReportedRoles"

    static let allRoles = ["intent_source", "runtime", "endpoint", "observer"]
    private static let defaultEnabledRoles = ["intent_source", "runtime", "endpoint"]
    private static let goproPreinstallKey = "livingroom.goproPreinstalled"

    static var clientHint: String {
        if let saved = UserDefaults.standard.string(forKey: hintKey), !saved.isEmpty {
            return saved
        }
        let suffix = UIDevice.current.identifierForVendor?.uuidString.prefix(8)
            ?? UUID().uuidString.prefix(8)
        let hint = "living-room-iphone-\(suffix)"
        UserDefaults.standard.set(hint, forKey: hintKey)
        return hint
    }

    static var participantId: String {
        get { UserDefaults.standard.string(forKey: idKey) ?? "" }
        set {
            let next = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            let prev = UserDefaults.standard.string(forKey: idKey) ?? ""
            UserDefaults.standard.set(next, forKey: idKey)
            if next.isEmpty || next != prev {
                UserDefaults.standard.removeObject(forKey: registeredAtKey)
            }
        }
    }

    static var registeredAt: Date? {
        get {
            let t = UserDefaults.standard.double(forKey: registeredAtKey)
            return t > 0 ? Date(timeIntervalSince1970: t) : nil
        }
        set {
            if let newValue {
                UserDefaults.standard.set(newValue.timeIntervalSince1970, forKey: registeredAtKey)
            } else {
                UserDefaults.standard.removeObject(forKey: registeredAtKey)
            }
        }
    }

    static var lastHeartbeatAt: Date? {
        get {
            let t = UserDefaults.standard.double(forKey: lastHeartbeatAtKey)
            return t > 0 ? Date(timeIntervalSince1970: t) : nil
        }
        set {
            if let newValue {
                UserDefaults.standard.set(newValue.timeIntervalSince1970, forKey: lastHeartbeatAtKey)
            } else {
                UserDefaults.standard.removeObject(forKey: lastHeartbeatAtKey)
            }
        }
    }

    static var lastRegisteredBrainURL: String {
        get { UserDefaults.standard.string(forKey: brainKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: brainKey) }
    }

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.2.0"
    }

    /// Roles queued for the next heartbeat (chip / settings). Not what Brain last received.
    static var reportedRoles: [String] {
        get {
            let saved = UserDefaults.standard.stringArray(forKey: rolesKey)
            let picked = (saved ?? defaultEnabledRoles).filter { allRoles.contains($0) }
            var ordered: [String] = []
            for role in allRoles where picked.contains(role) {
                ordered.append(role)
            }
            return ordered
        }
        set {
            UserDefaults.standard.set(
                allRoles.filter { newValue.contains($0) },
                forKey: rolesKey
            )
        }
    }

    /// Roles actually included in the last successful heartbeat.
    static var lastReportedRoles: [String] {
        get {
            let saved = UserDefaults.standard.stringArray(forKey: lastReportedRolesKey) ?? []
            return allRoles.filter { saved.contains($0) }
        }
        set {
            UserDefaults.standard.set(
                allRoles.filter { newValue.contains($0) },
                forKey: lastReportedRolesKey
            )
        }
    }

    /// One-shot: existing installs get runtime so camera.capture is advertised.
    static func applyGoProPreinstall() {
        guard !UserDefaults.standard.bool(forKey: goproPreinstallKey) else { return }
        setRole("runtime", enabled: true)
        UserDefaults.standard.set(true, forKey: goproPreinstallKey)
    }

    static func advertisedServices(roles: [String]? = nil) -> [[String: Any]] {
        let enabled = roles ?? reportedRoles
        guard enabled.contains("runtime") else { return [] }
        var services: [[String: Any]] = [
            goproCameraService,
            livingroomLightService,
            documentScannerService,
            iphoneVideoService,
            localAssetService,
        ]
        if HisenseCredentials.configured {
            let units = HisenseCredentials.boundDevices
            var seen = Set<String>()
            for unit in units {
                let name = unit.label.trimmingCharacters(in: .whitespacesAndNewlines)
                let label = name.isEmpty ? "海信空调" : name
                let sid = climateServiceId(for: label)
                if seen.contains(sid) { continue }
                seen.insert(sid)
                services.append(climateService(named: label))
            }
        }
        return services
    }

    private static let goproCameraService: [String: Any] = [
        "service_id": "gopro.camera",
        "display_name": "GoPro Camera",
        "version": "0.9.0",
        "group": "camera",
        "capabilities": [
            [
                "capability_id": "camera.capture",
                "kind": "input",
                "role": "拍照执行器",
                "planner_recognize": "按快门拍一张现场照（客厅、电视画面、眼前的东西），写入本机 inbox，产出 capture_ref（还不是 Asset）。允许当「给人看 / 问图上有什么 / 投电视」的前序步。本步不上传、不投屏、不能单步当最终图。下一步上传用 $capture_ref。禁止把 path 写进 plan",
                "typical_triggers": ["拍一张", "看看现在", "拍照", "拍张照", "拍的照片", "拍一下", "看看客厅电视画面", "拍一下电视屏幕"],
                "do_not_dispatch": ["上传", "传到图床", "传到云上", "单步作为最终给用户看的图", "放歌", "无拍照直接回答画面内容"],
                "input_schema": [:] as [String: [String: Any]],
                "output_schema": [
                    "capture_ref": [
                        "type": "string",
                        "required": true,
                        "description": "CaptureRef JSON {capture_id, type, mime_type}。本机 inbox 句柄，还不是 Asset。禁止 path / photo_url / asset_id。",
                    ],
                ],
            ],
        ],
    ]

    private static let livingroomLightService: [String: Any] = [
        "service_id": "livingroom.ceiling_light",
        "display_name": "客厅大路灯",
        "version": "0.1.1",
        "group": "light",
        "capabilities": [
            [
                "capability_id": "light.set",
                "kind": "action",
                "role": "灯光控制器",
                "planner_recognize": "开关家里的灯（客厅大灯、台灯）：开灯、关灯、调亮一点。入参 state=on/off。不是放歌、不是念一句话假装开灯",
                "typical_triggers": ["开灯", "关灯", "亮度 50", "台灯", "开台灯", "关台灯", "客厅灯", "打开灯", "开一下灯", "亮一点", "调亮", "调暗"],
                "do_not_dispatch": ["放歌", "TTS", "拍照"],
                "input_schema": [
                    "state": [
                        "type": "string",
                        "required": true,
                        "description": "on 开灯 / off 关灯；兼容 开、关、开灯、关灯",
                    ],
                ],
                "output_schema": [
                    "state": [
                        "type": "string",
                        "required": true,
                        "description": "规范化后的 on 或 off",
                    ],
                ],
            ],
        ],
    ]

    private static let documentScannerService: [String: Any] = [
        "service_id": "document.scanner",
        "display_name": "Document Scanner",
        "version": "0.2.1",
        "group": "document",
        "capabilities": [
            [
                "capability_id": "document.scan",
                "kind": "input",
                "role": "纸质文档扫描器",
                "planner_recognize": "用手机系统文档扫描拍纸质（小票、文件、作业），直接上传成 Image Asset。只负责扫进系统，不读字、不算金额、不总结、不投屏。读字要另排 OCR",
                "typical_triggers": ["扫描一下", "扫一下", "扫描一下这个小票", "扫一下文档", "扫一下作业"],
                "do_not_dispatch": ["OCR", "金额识别", "看图理解", "投屏", "开灯"],
                "input_schema": [
                    "mode": [
                        "type": "string",
                        "required": false,
                        "description": "默认 document",
                    ],
                ],
                "output_schema": [
                    "status": [
                        "type": "string",
                        "required": true,
                        "description": "completed 或 cancelled",
                    ],
                    "asset_ref": [
                        "type": "string",
                        "required": true,
                        "description": "Image AssetRef JSON。禁止 photo_url。",
                    ],
                ],
            ],
        ],
    ]

    private static let localAssetService: [String: Any] = [
        "service_id": "local.asset",
        "display_name": "Local Asset",
        "version": "0.2.0",
        "group": "asset",
        "capabilities": [
            [
                "capability_id": "asset.upload",
                "kind": "action",
                "role": "Asset 上传器",
                "planner_recognize": "不负责按快门。把本机 inbox 的 capture 或已有 Asset 传到家里图床/云端，产出可给后续步用的 asset_ref。拍完要给人看、给视觉问、投电视，必须另排本步，入参 $capture_ref。已有 Asset 再传一份用 asset_ref",
                "typical_triggers": [
                    "把这张图传到云上",
                    "传到家里图床",
                    "上传到图片服务器",
                    "把刚拍的照片传到图床",
                    "拍照后上传",
                ],
                "do_not_dispatch": ["拍照", "投屏", "看图理解", "Google Drive", "Dropbox"],
                "input_schema": [
                    "capture_ref": [
                        "type": "string",
                        "required": false,
                        "description": "本机 inbox CaptureRef JSON {capture_id, type, mime_type}。拍照后上传常为 $capture_ref。",
                    ],
                    "asset_ref": [
                        "type": "string",
                        "required": false,
                        "description": "已登记 Asset 的 AssetRef JSON。禁止 photo_url / path。已有 Asset 再传一份时用。",
                    ],
                    "dest": [
                        "type": "string",
                        "required": false,
                        "description": "img_server（默认）| cloud | gdrive | dropbox。gdrive/dropbox 本轮未实现。",
                    ],
                ],
                "output_schema": [
                    "asset_ref": [
                        "type": "string",
                        "required": true,
                        "description": "上传后的 AssetRef JSON。禁止 photo_url。",
                    ],
                    "dest": [
                        "type": "string",
                        "required": true,
                        "description": "img_server 或 cloud",
                    ],
                ],
            ],
        ],
    ]

    private static let iphoneVideoService: [String: Any] = [
        "service_id": "iphone.video",
        "display_name": "Video Live Stream",
        "version": "0.1.0",
        "group": "video",
        "capabilities": [
            [
                "capability_id": "video.live_stream",
                "kind": "input",
                "role": "iPhone 实时视频流入口",
                "planner_recognize": "把 iPhone 摄像头编成实时视频流推到 Mac。常驻推流，不是拍一张、不是看图问答、不要当 plan 逐步执行",
                "typical_triggers": ["开始直播", "推摄像头画面"],
                "do_not_dispatch": ["作为计划逐步执行", "看图理解", "抽帧上传", "投屏"],
                "input_schema": [String: Any](),
                "output_schema": [
                    "stream_id": [
                        "type": "string",
                        "required": false,
                        "description": "本次推流 id（观测用；不经计划逐步产出）",
                    ],
                ],
            ],
        ],
    ]

    private static func climateServiceId(for label: String) -> String {
        let name = label.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty { return "livingroom.climate" }
        switch name {
        case "客厅空调", "客厅海信空调": return "climate.living_room"
        case "儿童房空调", "儿童房": return "climate.kids_room"
        default:
            var hash: UInt64 = 5381
            for byte in name.utf8 {
                hash = ((hash &<< 5) &+ hash) &+ UInt64(byte)
            }
            return String(format: "climate.%08x", UInt32(truncatingIfNeeded: hash))
        }
    }

    private static func climateService(named name: String) -> [String: Any] {
        let namedTriggers = ["打开\(name)", "关掉\(name)", "关闭\(name)", "开\(name)", "关\(name)"]
        let generic = ["打开空调", "关掉空调", "制冷 26 度", "风速高", "左右扫风"]
        let extras = generic.filter { !namedTriggers.contains($0) }
        return [
            "service_id": climateServiceId(for: name),
            "display_name": name,
            "version": "0.1.0",
            "group": "climate",
            "capabilities": [
                [
                    "capability_id": "climate.set",
                    "kind": "action",
                    "role": "\(name)控制器",
                    "planner_recognize": "控制「\(name)」：开关、制冷/制热/送风、设定温度、风速、扫风。仅当用户点名该设备时使用本实例，不要派给其它同 capability 的在线节点。",
                    "typical_triggers": namedTriggers + extras,
                    "do_not_dispatch": ["放歌", "TTS", "开灯", "知识问答", "新风", "除湿"],
                    "input_schema": [
                        "power": [
                            "type": "string",
                            "required": false,
                            "description": "on / off；兼容 开、关、打开、关闭",
                        ],
                        "mode": [
                            "type": "string",
                            "required": false,
                            "description": "cool / heat / fan；兼容 制冷、制热、送风",
                        ],
                        "target_temp": [
                            "type": "number",
                            "required": false,
                            "description": "摄氏整数 16–32",
                        ],
                        "fan": [
                            "type": "string",
                            "required": false,
                            "description": "auto / diffuse / low / medium / high",
                        ],
                        "swing": [
                            "type": "string",
                            "required": false,
                            "description": "off / on / horizontal / vertical",
                        ],
                        "appliance": [
                            "type": "string",
                            "required": false,
                            "description": "绑定空调显示名，如 客厅空调、儿童房空调。本机绑定多台时必填。",
                        ],
                    ],
                    "output_schema": [
                        "power": [
                            "type": "string",
                            "required": true,
                            "description": "on 或 off",
                        ],
                        "mode": [
                            "type": "string",
                            "required": true,
                            "description": "当前模式",
                        ],
                        "status_text": [
                            "type": "string",
                            "required": true,
                            "description": "人类可读状态",
                        ],
                    ],
                ],
            ],
        ]
    }

    static func isRoleEnabled(_ role: String) -> Bool {
        reportedRoles.contains(role)
    }

    static func setRole(_ role: String, enabled: Bool) {
        guard allRoles.contains(role) else { return }
        var next = Set(reportedRoles)
        if enabled {
            next.insert(role)
        } else {
            next.remove(role)
        }
        reportedRoles = allRoles.filter { next.contains($0) }
    }

    static func registrationBody() -> [String: Any] {
        var body = identityFields()
        applyRoles(&body, reportedRoles)
        if isRoleEnabled("intent_source") {
            body["intent_sources"] = [
                ["source_id": "iphone.keyboard", "channel": "text"],
                ["source_id": "iphone.microphone", "channel": "voice"],
            ]
        } else {
            body["intent_sources"] = [] as [Any]
        }
        if isRoleEnabled("endpoint") {
            body["endpoints"] = [
                [
                    "endpoint_id": "iphone.display",
                    "type": "display",
                    "supported_presentation": ["image", "text"],
                ],
            ]
        } else {
            body["endpoints"] = [] as [Any]
        }
        body["services"] = advertisedServices()
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !pid.isEmpty {
            body["participant_id"] = pid
            body["edge_id"] = pid
        }
        return body
    }

    static func heartbeatBody(roles: [String]? = nil) -> [String: Any] {
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        let nowMs = Int64((Date().timeIntervalSince1970 * 1000.0).rounded())
        var body = identityFields()
        body["client_time_ms"] = NSNumber(value: nowMs)
        let enabled = roles ?? reportedRoles
        applyRoles(&body, enabled)
        if enabled.contains("intent_source") {
            body["intent_sources"] = [
                ["source_id": "iphone.keyboard", "channel": "text"],
                ["source_id": "iphone.microphone", "channel": "voice"],
            ]
        } else {
            body["intent_sources"] = [] as [Any]
        }
        if enabled.contains("endpoint") {
            body["endpoints"] = [
                [
                    "endpoint_id": "iphone.display",
                    "type": "display",
                    "supported_presentation": ["image", "text"],
                ],
            ]
        } else {
            body["endpoints"] = [] as [Any]
        }
        body["services"] = advertisedServices(roles: enabled)
        if !pid.isEmpty {
            body["edge_id"] = pid
            body["participant_id"] = pid
        }
        return body
    }

    private static func identityFields() -> [String: Any] {
        [
            "client_hint": clientHint,
            "display_name": "客厅 iPhone",
            "device_type": "iphone",
            "location": "living-room",
            "room": "living-room",
            "app_version": appVersion,
        ]
    }

    private static func applyRoles(_ body: inout [String: Any], _ enabled: [String]) {
        body["roles"] = enabled
        body["role_intent_source"] = enabled.contains("intent_source")
        body["role_runtime"] = enabled.contains("runtime")
        body["role_endpoint"] = enabled.contains("endpoint")
        body["role_observer"] = enabled.contains("observer")
    }
}
