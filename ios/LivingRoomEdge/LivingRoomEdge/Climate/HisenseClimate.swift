import Foundation

enum HisenseCredentials {
    private static let userKey = "livingroom.hisense.username"
    private static let passKey = "livingroom.hisense.password"
    private static let homeKey = "livingroom.hisense.homeId"
    private static let deviceKey = "livingroom.hisense.deviceId"
    private static let labelKey = "livingroom.hisense.deviceLabel"
    private static let devicesKey = "livingroom.hisense.boundDevices"

    struct BoundDevice: Codable, Identifiable, Equatable {
        var deviceId: String
        var label: String
        var homeId: String
        var id: String { deviceId }
    }

    static var username: String {
        get { UserDefaults.standard.string(forKey: userKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: userKey) }
    }

    static var password: String {
        get { UserDefaults.standard.string(forKey: passKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: passKey) }
    }

    /// Pending homeId for the next bind (does not wipe already-bound units).
    static var homeId: String {
        get { UserDefaults.standard.string(forKey: homeKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: homeKey) }
    }

    /// Pending deviceId for the next bind.
    static var deviceId: String {
        get { UserDefaults.standard.string(forKey: deviceKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: deviceKey) }
    }

    static var deviceLabel: String {
        get { UserDefaults.standard.string(forKey: labelKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: labelKey) }
    }

    static var boundDevices: [BoundDevice] {
        get {
            migrateLegacyIfNeeded()
            guard let data = UserDefaults.standard.data(forKey: devicesKey),
                  let rows = try? JSONDecoder().decode([BoundDevice].self, from: data)
            else { return [] }
            return rows.filter { !$0.deviceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !$0.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        }
        set {
            let data = (try? JSONEncoder().encode(newValue)) ?? Data()
            UserDefaults.standard.set(data, forKey: devicesKey)
        }
    }

    static var boundApplianceName: String {
        if let first = boundDevices.first {
            let label = first.label.trimmingCharacters(in: .whitespacesAndNewlines)
            return label.isEmpty ? "海信空调" : label
        }
        let label = deviceLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        return label.isEmpty ? "海信空调" : label
    }

    static var boundApplianceNames: [String] {
        let names = boundDevices.map { row -> String in
            let label = row.label.trimmingCharacters(in: .whitespacesAndNewlines)
            return label.isEmpty ? row.deviceId : label
        }.filter { !$0.isEmpty }
        return names
    }

    static var configured: Bool {
        !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !password.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func addBoundDevice(deviceId: String, label: String, homeId: String) {
        let did = deviceId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !did.isEmpty else { return }
        var rows = boundDevices
        rows.removeAll { $0.deviceId == did }
        rows.append(BoundDevice(deviceId: did, label: label, homeId: homeId))
        boundDevices = rows
        deviceLabel = label
        self.deviceId = did
        self.homeId = homeId
    }

    static func removeBoundDevice(deviceId: String) {
        let did = deviceId.trimmingCharacters(in: .whitespacesAndNewlines)
        var rows = boundDevices
        rows.removeAll { $0.deviceId == did }
        boundDevices = rows
        if deviceId == self.deviceId || rows.isEmpty {
            self.deviceId = rows.last?.deviceId ?? ""
            deviceLabel = rows.last?.label ?? ""
            homeId = rows.last?.homeId ?? homeId
        }
    }

    private static func migrateLegacyIfNeeded() {
        if UserDefaults.standard.data(forKey: devicesKey) != nil { return }
        let did = (UserDefaults.standard.string(forKey: deviceKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let label = (UserDefaults.standard.string(forKey: labelKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let hid = (UserDefaults.standard.string(forKey: homeKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !did.isEmpty || !label.isEmpty else { return }
        let row = BoundDevice(deviceId: did, label: label, homeId: hid)
        if let data = try? JSONEncoder().encode([row]) {
            UserDefaults.standard.set(data, forKey: devicesKey)
        }
    }
}

enum HisenseAcError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case let .message(s): return s
        }
    }
}

enum HisenseClimate {
    private static let tempMin = 16
    private static let tempMax = 32
    private static let powerOnWaitNs: UInt64 = 4_000_000_000

    struct Request {
        var power: String?
        var mode: String?
        var targetTemp: Int?
        var fan: String?
        var swing: String?
    }

    private static let onAliases: Set<String> = [
        "on", "开", "打开", "开机", "开空调", "true", "1",
    ]
    private static let offAliases: Set<String> = [
        "off", "关", "关闭", "关机", "关空调", "关掉", "false", "0",
    ]
    private static let modeAliases: [String: String] = [
        "cool": "cool", "制冷": "cool", "cold": "cool",
        "heat": "heat", "制热": "heat", "加热": "heat",
        "fan": "fan", "送风": "fan", "通风": "fan", "fan_only": "fan",
    ]
    private static let fanAliases: [String: String] = [
        "auto": "auto", "自动": "auto", "自动风": "auto",
        "diffuse": "diffuse", "柔风": "diffuse", "散风": "diffuse",
        "low": "low", "低": "low", "低风": "low", "低速": "low", "小风": "low",
        "medium": "medium", "med": "medium", "中": "medium", "中风": "medium", "中速": "medium",
        "high": "high", "高": "high", "高风": "high", "高速": "high", "大风": "high",
    ]
    private static let swingAliases: [String: String] = [
        "off": "off", "关": "off", "关闭": "off", "停止": "off", "停": "off",
        "关扫风": "off", "停止扫风": "off", "false": "off", "0": "off",
        "on": "on", "开": "on", "打开": "on", "开扫风": "on", "扫风": "on", "true": "on", "1": "on",
        "horizontal": "horizontal", "左右": "horizontal", "左右扫": "horizontal",
        "左右扫风": "horizontal", "水平": "horizontal",
        "vertical": "vertical", "上下": "vertical", "上下扫": "vertical",
        "上下扫风": "vertical", "垂直": "vertical",
    ]
    private static let modeToId: [String: Int] = [
        "fan": HisenseCloud.hvacFan, "heat": HisenseCloud.hvacHeat, "cool": HisenseCloud.hvacCool,
    ]
    private static let fanToId: [String: Int] = [
        "auto": HisenseCloud.fanAuto, "diffuse": HisenseCloud.fanDiffuse,
        "low": HisenseCloud.fanLow, "medium": HisenseCloud.fanMedium, "high": HisenseCloud.fanHigh,
    ]
    private static let swingToId: [String: Int] = [
        "off": HisenseCloud.swingOff, "on": HisenseCloud.swingOn,
        "horizontal": HisenseCloud.swingHorizontal, "vertical": HisenseCloud.swingVertical,
    ]
    private static let modeLabels = ["cool": "制冷", "heat": "制热", "fan": "送风", "dry": "除湿", "auto": "自动"]
    private static let fanLabels = [
        "auto": "风速自动", "diffuse": "柔风", "low": "风速低", "medium": "风速中", "high": "风速高",
    ]
    private static let swingLabels = [
        "off": "扫风关", "on": "扫风开", "horizontal": "左右扫风", "vertical": "上下扫风",
    ]

    static func run(params: [String: Any]) async throws -> (message: String, outputs: [String: Any]) {
        let req = try parse(params)
        let ac = try await connect(params: params)
        let outputs = try await apply(req, ac: ac)
        let msg = "climate.set \(outputs["status_text"] as? String ?? "")"
        NSLog("[HisenseClimate] %@", msg)
        return (msg, outputs)
    }

    static func parse(_ params: [String: Any]) throws -> Request {
        let power = try normalizePower(params["power"])
        let mode = try normalizeMode(params["mode"])
        let targetTemp = try normalizeTemp(params["target_temp"])
        let fan = try normalizeFan(params["fan"])
        let swing = try normalizeSwing(params["swing"])
        if power == nil, mode == nil, targetTemp == nil, fan == nil, swing == nil {
            throw HisenseAcError.message(
                "空调控制失败：缺少入参。请至少提供 power、mode、target_temp、fan 或 swing 之一。"
            )
        }
        let extras = mode != nil || targetTemp != nil || fan != nil || swing != nil
        if power == "off", extras {
            throw HisenseAcError.message("空调控制失败：关机时不能同时设定模式、温度、风速或扫风。")
        }
        if mode == "fan", targetTemp != nil {
            throw HisenseAcError.message("空调控制失败：送风模式不能设定温度。")
        }
        return Request(power: power, mode: mode, targetTemp: targetTemp, fan: fan, swing: swing)
    }

    private static func fold(_ raw: Any?) -> String? {
        guard let raw else { return nil }
        let s = String(describing: raw).trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "")
        return s.isEmpty ? nil : s
    }

    private static func normalizePower(_ raw: Any?) throws -> String? {
        guard let folded = fold(raw) else { return nil }
        if onAliases.contains(folded) { return "on" }
        if offAliases.contains(folded) { return "off" }
        throw HisenseAcError.message("空调控制失败：无法识别 power「\(String(describing: raw))」。请用 on 或 off。")
    }

    private static func normalizeMode(_ raw: Any?) throws -> String? {
        guard let folded = fold(raw) else { return nil }
        guard let mapped = modeAliases[folded] else {
            throw HisenseAcError.message("空调控制失败：无法识别 mode「\(String(describing: raw))」。请用 cool、heat 或 fan。")
        }
        return mapped
    }

    private static func normalizeTemp(_ raw: Any?) throws -> Int? {
        guard let raw else { return nil }
        if raw is Bool {
            throw HisenseAcError.message("空调控制失败：target_temp 必须是摄氏整数。")
        }
        var text = String(describing: raw).trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return nil }
        text = text.replacingOccurrences(of: "℃", with: "")
            .replacingOccurrences(of: "°C", with: "")
            .replacingOccurrences(of: "度", with: "")
        guard let value = Double(text), value == Double(Int(value)) else {
            throw HisenseAcError.message("空调控制失败：无法识别 target_temp「\(raw)」。请用 16 到 32 的整数。")
        }
        let temp = Int(value)
        guard (tempMin ... tempMax).contains(temp) else {
            throw HisenseAcError.message("空调控制失败：温度 \(temp) 超出范围（\(tempMin)–\(tempMax)）。")
        }
        return temp
    }

    private static func normalizeFan(_ raw: Any?) throws -> String? {
        guard let folded = fold(raw) else { return nil }
        guard let mapped = fanAliases[folded] else {
            throw HisenseAcError.message(
                "空调控制失败：无法识别 fan「\(String(describing: raw))」。请用 auto、diffuse、low、medium 或 high。"
            )
        }
        return mapped
    }

    private static func normalizeSwing(_ raw: Any?) throws -> String? {
        guard let folded = fold(raw) else { return nil }
        guard let mapped = swingAliases[folded] else {
            throw HisenseAcError.message(
                "空调控制失败：无法识别 swing「\(String(describing: raw))」。请用 off、on、horizontal 或 vertical。"
            )
        }
        return mapped
    }

    /// Settings「验证并绑定」：登录爱家并解析出空调，追加到本机绑定列表，不覆盖已有。
    static func probeBind() async throws -> String {
        let hit = try await resolveDevice(params: [:], forBind: true)
        HisenseCredentials.addBoundDevice(
            deviceId: hit.device.deviceId,
            label: hit.device.label,
            homeId: hit.home.homeId
        )
        let names = HisenseCredentials.boundApplianceNames.joined(separator: "、")
        return "已绑定 \(hit.device.label)（homeId=\(hit.home.homeId)，deviceId=\(hit.device.deviceId)）。本机现有：\(names)"
    }

    private static func connect(params: [String: Any] = [:]) async throws -> HisenseAC {
        let hit = try await resolveDevice(params: params, forBind: false)
        return HisenseAC(
            http: hit.http,
            wifiId: hit.device.wifiId,
            deviceId: hit.device.deviceId,
            accessToken: hit.tokens.access,
            refreshToken: hit.tokens.refresh,
            refresher: hit.session
        )
    }

    private struct ResolvedDevice {
        let http: HisenseHttp
        let session: HisenseSession
        let tokens: (access: String, refresh: String)
        let home: HisenseCloud.Home
        let device: HisenseCloud.Device
    }

    private static func boundTarget(from params: [String: Any], forBind: Bool) throws -> (deviceId: String, homeId: String) {
        let bound = HisenseCredentials.boundDevices
        let appliance = [
            params["appliance"], params["label"], params["display_name"],
        ].compactMap { $0 as? String }.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty } ?? ""
        let paramDevice = [
            params["device_id"], params["deviceId"],
        ].compactMap { $0 as? String }.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty } ?? ""
        if forBind {
            return (
                HisenseCredentials.deviceId.trimmingCharacters(in: .whitespacesAndNewlines),
                HisenseCredentials.homeId.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        }
        if !paramDevice.isEmpty {
            if let hit = bound.first(where: { $0.deviceId == paramDevice }) {
                return (hit.deviceId, hit.homeId)
            }
            return (paramDevice, HisenseCredentials.homeId.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        if !appliance.isEmpty {
            if let hit = bound.first(where: {
                let label = $0.label.trimmingCharacters(in: .whitespacesAndNewlines)
                return !label.isEmpty && (appliance == label || appliance.contains(label) || label.contains(appliance))
            }) {
                return (hit.deviceId, hit.homeId)
            }
            let listed = HisenseCredentials.boundApplianceNames.joined(separator: "、")
            throw HisenseAcError.message("空调控制失败：未绑定「\(appliance)」。已绑定：\(listed.isEmpty ? "（无）" : listed)。")
        }
        if bound.count == 1 {
            return (bound[0].deviceId, bound[0].homeId)
        }
        if bound.count > 1 {
            let listed = HisenseCredentials.boundApplianceNames.joined(separator: "、")
            throw HisenseAcError.message("空调控制失败：未指定要控制哪台空调。请说名称。已绑定：\(listed)。")
        }
        return (
            HisenseCredentials.deviceId.trimmingCharacters(in: .whitespacesAndNewlines),
            HisenseCredentials.homeId.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    private static func resolveDevice(params: [String: Any] = [:], forBind: Bool = false) async throws -> ResolvedDevice {
        let username = HisenseCredentials.username.trimmingCharacters(in: .whitespacesAndNewlines)
        let password = HisenseCredentials.password.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !username.isEmpty, !password.isEmpty else {
            throw HisenseAcError.message("空调控制失败：未配置海信爱家账号（设置 → 海信空调）。")
        }
        let target = try boundTarget(from: params, forBind: forBind)
        let homeWanted = target.homeId
        let deviceWanted = target.deviceId
        let http = HisenseHttp()
        let session = HisenseSession(http: http)
        do {
            let tokens = try await session.login(username: username, password: password)
            let homes = try await session.listHomes(accessToken: tokens.access)
            let home = try pickHome(homes, wanted: homeWanted)
            let devices = try await session.listACDevices(accessToken: tokens.access, homeId: home.homeId)
            let device = try pickDevice(devices, wanted: deviceWanted)
            NSLog(
                "[HisenseClimate] connect home=%@ device=%@ label=%@",
                home.homeId, device.deviceId, device.label
            )
            return ResolvedDevice(
                http: http,
                session: session,
                tokens: (tokens.access, tokens.refresh),
                home: home,
                device: device
            )
        } catch let e as HisenseCloudError {
            throw HisenseAcError.message(e.localizedDescription)
        }
    }

    private static func pickHome(_ homes: [HisenseCloud.Home], wanted: String) throws -> HisenseCloud.Home {
        guard !homes.isEmpty else {
            throw HisenseAcError.message("空调控制失败：爱家账号下没有家庭。")
        }
        if !wanted.isEmpty {
            if let hit = homes.first(where: { $0.homeId == wanted }) { return hit }
            throw HisenseAcError.message("空调控制失败：找不到家庭 \(wanted)。")
        }
        if homes.count == 1 { return homes[0] }
        let names = homes.map { "\($0.name)(\($0.homeId))" }.joined(separator: "、")
        throw HisenseAcError.message("空调控制失败：账号下有多个家庭，请在设置里填写 homeId。候选：\(names)")
    }

    private static func pickDevice(_ devices: [HisenseCloud.Device], wanted: String) throws -> HisenseCloud.Device {
        guard !devices.isEmpty else {
            throw HisenseAcError.message("空调控制失败：这个家庭里没有海信空调。")
        }
        if !wanted.isEmpty {
            if let hit = devices.first(where: { $0.deviceId == wanted }) { return hit }
            throw HisenseAcError.message("空调控制失败：找不到空调 \(wanted)。")
        }
        if devices.count == 1 { return devices[0] }
        let names = devices.map { "\($0.label)(\($0.deviceId))" }.joined(separator: "、")
        throw HisenseAcError.message("空调控制失败：有多台空调，请在设置里填写 deviceId。候选：\(names)")
    }

    private static func apply(_ req: Request, ac: HisenseAC) async throws -> [String: Any] {
        if req.power == "off" {
            guard try await ac.turnOff() else {
                throw HisenseAcError.message("空调关闭失败：海信云端拒绝关机。")
            }
            let status = (try await ac.checkStatus()) ?? [:]
            return outputsFromStatus(status, req: req)
        }
        guard let status = try await ac.checkStatus() else {
            throw HisenseAcError.message("空调控制失败：无法读取当前状态。")
        }
        let wasOn = (status["power_on"] as? Bool) == true
        let needLogic = req.mode != nil || req.targetTemp != nil || req.fan != nil || req.swing != nil
        let needOn = req.power == "on" || needLogic
        var turnedOn = false
        if needOn, !wasOn {
            guard try await ac.turnOn() else {
                throw HisenseAcError.message("空调开启失败：海信云端拒绝开机。")
            }
            turnedOn = true
        }
        if needLogic {
            if turnedOn {
                try await Task.sleep(nanoseconds: powerOnWaitNs)
            }
            if let mode = req.mode, let mid = modeToId[mode] {
                guard try await ac.sendLogicCommand(cmdId: HisenseCloud.cmdHvacMode, param: mid) else {
                    throw HisenseAcError.message("空调改模式失败：海信云端拒绝。")
                }
            }
            if let temp = req.targetTemp {
                guard try await ac.sendLogicCommand(cmdId: HisenseCloud.cmdTemp, param: temp) else {
                    throw HisenseAcError.message("空调设温失败：海信云端拒绝。")
                }
            }
            if let fan = req.fan, let fid = fanToId[fan] {
                guard try await ac.sendLogicCommand(cmdId: HisenseCloud.cmdFan, param: fid) else {
                    throw HisenseAcError.message("空调改风速失败：海信云端拒绝。")
                }
            }
            if let swing = req.swing, let sid = swingToId[swing] {
                guard try await ac.sendLogicCommand(cmdId: HisenseCloud.cmdSwing, param: sid) else {
                    throw HisenseAcError.message("空调改扫风失败：海信云端拒绝。")
                }
            }
        }
        let final = (try await ac.checkStatus()) ?? [:]
        return outputsFromStatus(final, req: req)
    }

    private static func outputsFromStatus(_ status: [String: Any], req: Request? = nil) -> [String: Any] {
        var power = (status["power_on"] as? Bool) == true ? "on" : "off"
        var mode = (status["mode"] as? String)
            ?? HisenseCloud.idToMode[status["hvac_mode_id"] as? Int ?? -1]
            ?? "auto"
        var fan = status["fan"] as? String
            ?? HisenseCloud.idToFan[status["fan_mode_id"] as? Int ?? -1]
        var swing = status["swing"] as? String
            ?? HisenseCloud.idToSwing[status["swing_mode_id"] as? Int ?? -1]
        var target = intValue(status["desired_temperature"])
        let indoor = intValue(status["indoor_temperature"])
        if let req {
            if let p = req.power, p == "on" || p == "off" {
                power = p
            } else if req.mode != nil || req.targetTemp != nil || req.fan != nil || req.swing != nil {
                power = "on"
            }
            if let modeReq = req.mode { mode = modeReq }
            if let temp = req.targetTemp { target = temp }
            if let fanReq = req.fan { fan = fanReq }
            if let swingReq = req.swing { swing = swingReq }
        }
        let shownTemp = (power == "off" || mode == "fan") ? nil : target
        var out: [String: Any] = [
            "power": power,
            "mode": mode,
            "status_text": statusText(power: power, mode: mode, targetTemp: shownTemp, fan: fan, swing: swing),
        ]
        if let target { out["target_temp"] = target }
        if let indoor { out["indoor_temp"] = indoor }
        if let fan { out["fan"] = fan }
        if let swing { out["swing"] = swing }
        return out
    }

    private static func intValue(_ raw: Any?) -> Int? {
        if let i = raw as? Int { return i }
        if let n = raw as? NSNumber { return n.intValue }
        if let d = raw as? Double { return Int(d) }
        return nil
    }

    private static func statusText(
        power: String,
        mode: String,
        targetTemp: Int?,
        fan: String?,
        swing: String?
    ) -> String {
        if power == "off" { return "空调已关" }
        var parts = ["空调已开"]
        let modeLabel = modeLabels[mode] ?? mode
        if let targetTemp, mode != "fan" {
            parts.append("\(modeLabel) \(targetTemp)°C")
        } else {
            parts.append(modeLabel)
        }
        if let fan, let label = fanLabels[fan] { parts.append(label) }
        if let swing, let label = swingLabels[swing] { parts.append(label) }
        return parts.joined(separator: "，")
    }
}
