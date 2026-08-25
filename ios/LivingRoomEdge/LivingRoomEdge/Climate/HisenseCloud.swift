import Foundation
import CommonCrypto
import CryptoKit

private let kHisensePortalAppKey = "commonweb"
private let kHisensePortalAppSecret = "MORZRbkuiWxjp+SM4vR_GxY4pZxLZ6rn"
private let kHisenseAppUA =
    "%E6%B5%B7%E4%BF%A1%E6%99%BA%E6%85%A7%E5%AE%B6/4 CFNetwork/1492.0.1 Darwin/23.3.0"

enum HisenseCloudError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case let .message(s): return s
        }
    }
}

enum HisenseCloud {
    static let portalLoginURL = "https://portal-account.hismarttv.com/mobile/se/signon"
    static let homeListURL = "https://api-wg.hismarttv.com/wg/dm/getHomeList"
    static let deviceListURL = "https://api-wg.hismarttv.com/wg/dm/getHomeDeviceList"
    static let outerHead = "https://api-wg.hismarttv.com/agw/dsg/outer"
    static let powerPath = "/sendDeviceModelCmd?accessToken="
    static let commandPath = "/uploadRemoteLogicCmd?accessToken="
    static let statusPath = "/getDeviceLogicalStatusArray?accessToken="
    static let refreshURL = "https://bas-wg.hismarttv.com/aaa/refresh_token2"

    /// Aliases for call sites (same values as file-level constants).
    static var portalAppKey: String { kHisensePortalAppKey }
    static var portalAppSecret: String { kHisensePortalAppSecret }
    static var appUA: String { kHisenseAppUA }

    static let cmdFan = 1
    static let cmdHvacMode = 3
    static let cmdTemp = 6
    static let cmdSwing = 62

    static let hvacFan = 0
    static let hvacHeat = 1
    static let hvacCool = 2

    static let fanAuto = 0
    static let fanDiffuse = 1
    static let fanLow = 2
    static let fanMedium = 3
    static let fanHigh = 4

    static let swingOff = 0
    static let swingOn = 1
    static let swingHorizontal = 2
    static let swingVertical = 3

    static let idToMode: [Int: String] = [
        0: "fan", 1: "heat", 2: "cool", 3: "dry", 4: "auto",
    ]
    static let idToFan: [Int: String] = [
        0: "auto", 1: "diffuse", 2: "low", 3: "medium", 4: "high",
    ]
    static let idToSwing: [Int: String] = [
        0: "off", 1: "on", 2: "horizontal", 3: "vertical",
    ]

    struct Home {
        let homeId: String
        let name: String
    }

    struct Device {
        let deviceId: String
        let wifiId: String
        let label: String
    }

    static func portalEncrypt(_ value: String) throws -> String {
        let key = Array(kHisensePortalAppSecret.utf8)
        let iv = Array(kHisensePortalAppSecret.utf8.prefix(16))
        guard key.count == 32, iv.count == 16 else {
            throw HisenseCloudError.message("海信门户加密密钥无效")
        }
        return try aesCBCEncryptPKCS7(value: value, key: key, iv: iv)
    }

    private static func aesCBCEncryptPKCS7(value: String, key: [UInt8], iv: [UInt8]) throws -> String {
        let data = Array(value.utf8)
        var outLength = data.count + kCCBlockSizeAES128
        var out = [UInt8](repeating: 0, count: outLength)
        let status = CCCrypt(
            CCOperation(kCCEncrypt),
            CCAlgorithm(kCCAlgorithmAES),
            CCOptions(kCCOptionPKCS7Padding),
            key, key.count,
            iv,
            data, data.count,
            &out, out.count,
            &outLength
        )
        guard status == kCCSuccess else {
            throw HisenseCloudError.message("海信门户 AES 加密失败 (\(status))")
        }
        return Data(out.prefix(outLength)).base64EncodedString()
    }

    static func portalSign(_ body: String) -> String {
        let digest = Insecure.MD5.hash(data: Data((body + kHisensePortalAppSecret).utf8))
        return Data(digest).base64EncodedString()
    }

    static func timestampMs() -> Int64 {
        Int64((Date().timeIntervalSince1970 * 1000.0).rounded())
    }

    /// Compact JSON matching Python `separators=(",", ":")` with stable key order for portal sign.
    static func compactJSONObject(_ pairs: [(String, Any)]) throws -> String {
        var parts: [String] = []
        for (key, value) in pairs {
            let keyJSON = try jsonString(key)
            let valueJSON: String
            switch value {
            case let s as String:
                valueJSON = try jsonString(s)
            case let i as Int:
                valueJSON = String(i)
            case let n as NSNumber:
                valueJSON = n.stringValue
            default:
                let data = try JSONSerialization.data(withJSONObject: value)
                valueJSON = String(data: data, encoding: .utf8) ?? "null"
            }
            parts.append("\(keyJSON):\(valueJSON)")
        }
        return "{\(parts.joined(separator: ","))}"
    }

    private static func jsonString(_ s: String) throws -> String {
        // Bare String is not a valid top-level JSONSerialization object — wrap then strip.
        let data = try JSONSerialization.data(withJSONObject: [s])
        guard let wrapped = String(data: data, encoding: .utf8),
              wrapped.count >= 2,
              wrapped.first == "[",
              wrapped.last == "]"
        else {
            throw HisenseCloudError.message("JSON 编码失败")
        }
        return String(wrapped.dropFirst().dropLast())
    }

    static func parseStatusCSV(_ payload: String) throws -> [String: Any] {
        let values = payload.split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
        guard values.count >= 210 else {
            throw HisenseCloudError.message(
                "空调状态解析失败：云端返回 \(values.count) 项，期望至少 210 项。"
            )
        }
        let fanModeId = values[0]
        let hvacModeId = values[4]
        let swingModeId = values[209]
        guard let mode = idToMode[hvacModeId] else {
            throw HisenseCloudError.message("空调状态解析失败：未知模式 id \(hvacModeId)。")
        }
        guard let fan = idToFan[fanModeId] else {
            throw HisenseCloudError.message("空调状态解析失败：未知风速 id \(fanModeId)。")
        }
        guard let swing = idToSwing[swingModeId] else {
            throw HisenseCloudError.message("空调状态解析失败：未知扫风 id \(swingModeId)。")
        }
        return [
            "power_on": values[5] == 1,
            "hvac_mode_id": hvacModeId,
            "mode": mode,
            "desired_temperature": values[9],
            "indoor_temperature": values[10],
            "fan_mode_id": fanModeId,
            "fan": fan,
            "swing_mode_id": swingModeId,
            "swing": swing,
        ]
    }

    static func extractStatusPayload(_ result: [String: Any]) throws -> String {
        guard let response = result["response"] as? [String: Any] else {
            throw HisenseCloudError.message("空调云端响应缺少 response。")
        }
        if let pre = response["preStatus"] as? String, !pre.isEmpty {
            return pre
        }
        if let list = response["deviceStatusList"] as? [[String: Any]],
           let first = list.first,
           let status = first["deviceStatus"] as? String,
           !status.isEmpty {
            return status
        }
        throw HisenseCloudError.message("空调云端响应缺少状态字段。")
    }

    static func deviceLabel(_ item: [String: Any], deviceId: String) -> String {
        let room = (item["roomName"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let nick = (item["deviceNickName"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !room.isEmpty, !nick.isEmpty { return "\(room)-\(nick)" }
        if !room.isEmpty { return room }
        if !nick.isEmpty { return nick }
        let name = (item["deviceName"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? deviceId : name
    }
}

final class HisenseHttp {
    func postJSON(
        url: String,
        headers: [String: String] = [:],
        query: [String: String] = [:],
        body: Data? = nil,
        form: [String: String]? = nil
    ) async throws -> Any {
        guard var components = URLComponents(string: url) else {
            throw HisenseCloudError.message("无效 URL")
        }
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let finalURL = components.url else {
            throw HisenseCloudError.message("无效 URL")
        }
        var request = URLRequest(url: finalURL)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        for (k, v) in headers {
            request.setValue(v, forHTTPHeaderField: k)
        }
        if let form {
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            let encoded = form.map {
                "\(escape($0.key))=\(escape($0.value))"
            }.joined(separator: "&")
            request.httpBody = encoded.data(using: .utf8)
        } else if let body {
            request.httpBody = body
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200 ..< 300).contains(http.statusCode) else {
                throw HisenseCloudError.message("海信云端 HTTP 失败")
            }
            return try JSONSerialization.jsonObject(with: data)
        } catch let e as HisenseCloudError {
            throw e
        } catch {
            throw HisenseCloudError.message("海信云端请求失败：\(error.localizedDescription)")
        }
    }

    func getJSON(url: String, query: [String: String]) async throws -> Any {
        guard var components = URLComponents(string: url) else {
            throw HisenseCloudError.message("无效 URL")
        }
        components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        guard let finalURL = components.url else {
            throw HisenseCloudError.message("无效 URL")
        }
        var request = URLRequest(url: finalURL)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200 ..< 300).contains(http.statusCode) else {
                throw HisenseCloudError.message("海信云端 HTTP 失败")
            }
            return try JSONSerialization.jsonObject(with: data)
        } catch let e as HisenseCloudError {
            throw e
        } catch {
            throw HisenseCloudError.message("海信云端请求失败：\(error.localizedDescription)")
        }
    }

    private func escape(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? s
    }
}

final class HisenseSession {
    let http: HisenseHttp

    init(http: HisenseHttp = HisenseHttp()) {
        self.http = http
    }

    func login(username: String, password: String) async throws -> (access: String, refresh: String) {
        let body = try HisenseCloud.compactJSONObject([
            ("loginName", try HisenseCloud.portalEncrypt(username)),
            ("signature", try HisenseCloud.portalEncrypt(password)),
            ("serverCode", "9501"),
            ("distributeId", "2001"),
            ("termType", 2),
        ])
        let headers = [
            "Content-Type": "application/json; charset=UTF-8",
            "appKey": kHisensePortalAppKey,
            "X-Sign-For": HisenseCloud.portalSign(body),
        ]
        let params = [
            "lastUpdateTime": "0",
            "version": "1.0",
            "deviceType": "2",
            "appType": "100",
            "versionCode": "101",
            "adaptertRank": "720",
            "_": String(HisenseCloud.timestampMs()),
        ]
        let result = try await http.postJSON(
            url: HisenseCloud.portalLoginURL,
            headers: headers,
            query: params,
            body: Data(body.utf8)
        )
        guard let root = result as? [String: Any],
              let payload = root["data"] as? [String: Any],
              (payload["resultCode"] as? Int) == 0 || (payload["resultCode"] as? NSNumber)?.intValue == 0,
              let tokenInfo = payload["tokenInfo"] as? [String: Any],
              let access = tokenInfo["token"] as? String,
              let refresh = tokenInfo["refreshToken"] as? String,
              !access.isEmpty, !refresh.isEmpty
        else {
            throw HisenseCloudError.message("海信爱家登录失败：用户名或密码不对。")
        }
        return (access, refresh)
    }

    func listHomes(accessToken: String) async throws -> [HisenseCloud.Home] {
        let params = [
            "sign": "",
            "languageId": "0",
            "version": "8.0",
            "accessToken": accessToken,
            "timezone": "28800",
            "format": "1",
            "timeStamp": String(HisenseCloud.timestampMs()),
        ]
        let result = try await http.getJSON(url: HisenseCloud.homeListURL, query: params)
        guard let root = result as? [String: Any],
              let response = root["response"] as? [String: Any],
              (response["resultCode"] as? Int) == 0 || (response["resultCode"] as? NSNumber)?.intValue == 0
        else {
            throw HisenseCloudError.message("海信爱家列出家庭失败。")
        }
        var homes: [HisenseCloud.Home] = []
        for item in response["homeList"] as? [[String: Any]] ?? [] {
            let hid = Self.stringField(item["homeId"])
            guard !hid.isEmpty else { continue }
            let name = (item["homeName"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            homes.append(.init(homeId: hid, name: (name?.isEmpty == false ? name! : hid)))
        }
        return homes
    }

    func listACDevices(accessToken: String, homeId: String) async throws -> [HisenseCloud.Device] {
        let params = [
            "sign": "",
            "languageId": "0",
            "version": "8.0",
            "accessToken": accessToken,
            "homeId": homeId,
            "timezone": "28800",
            "format": "1",
            "timeStamp": String(HisenseCloud.timestampMs()),
        ]
        let result = try await http.getJSON(url: HisenseCloud.deviceListURL, query: params)
        guard let root = result as? [String: Any],
              let response = root["response"] as? [String: Any],
              (response["resultCode"] as? Int) == 0 || (response["resultCode"] as? NSNumber)?.intValue == 0
        else {
            throw HisenseCloudError.message("海信爱家列出设备失败。")
        }
        var devices: [HisenseCloud.Device] = []
        for item in response["deviceList"] as? [[String: Any]] ?? [] {
            let typeName = item["deviceTypeName"] as? String ?? ""
            guard typeName.contains("空调") else { continue }
            let did = Self.stringField(item["deviceId"])
            let wifi = Self.stringField(item["wifiId"])
            guard !did.isEmpty, !wifi.isEmpty else { continue }
            devices.append(
                .init(deviceId: did, wifiId: wifi, label: HisenseCloud.deviceLabel(item, deviceId: did))
            )
        }
        return devices
    }

    private static func stringField(_ raw: Any?) -> String {
        if let s = raw as? String {
            return s.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let n = raw as? NSNumber {
            return n.stringValue
        }
        if let i = raw as? Int {
            return String(i)
        }
        return ""
    }

    func refreshAccessToken(refreshToken: String) async throws -> String {
        let result = try await http.postJSON(
            url: HisenseCloud.refreshURL,
            headers: [
                "User-Agent": kHisenseAppUA,
                "Accept": "*/*",
            ],
            form: [
                "refreshToken": refreshToken,
                "appKey": "1234567890",
                "format": "1",
            ]
        )
        guard let arr = result as? [[String: Any]],
              let first = arr.first,
              let token = first["token"] as? String,
              !token.isEmpty
        else {
            throw HisenseCloudError.message("海信爱家刷新 token 失败。")
        }
        return token
    }
}

final class HisenseAC {
    let http: HisenseHttp
    let wifiId: String
    let deviceId: String
    var accessToken: String
    let refreshToken: String
    let refresher: HisenseSession
    var status: [String: Any] = ["power_on": false]

    private var headers: [String: String] {
        [
            "Content-Type": "application/json",
            "Accept": "*/*",
            "User-Agent": kHisenseAppUA,
        ]
    }

    init(
        http: HisenseHttp,
        wifiId: String,
        deviceId: String,
        accessToken: String,
        refreshToken: String,
        refresher: HisenseSession
    ) {
        self.http = http
        self.wifiId = wifiId
        self.deviceId = deviceId
        self.accessToken = accessToken
        self.refreshToken = refreshToken
        self.refresher = refresher
    }

    private func powerURL() -> String { HisenseCloud.outerHead + HisenseCloud.powerPath + accessToken }
    private func commandURL() -> String { HisenseCloud.outerHead + HisenseCloud.commandPath + accessToken }
    private func statusURL() -> String { HisenseCloud.outerHead + HisenseCloud.statusPath + accessToken }

    private func powerBody() -> [String: Any] {
        ["wifiId": wifiId, "deviceId": deviceId, "extendParam": "1", "cmdVersion": "0"]
    }

    private func commandBody() -> [String: Any] {
        ["wifiId": wifiId, "deviceId": deviceId, "extendParm": "1", "cmdVersion": "1684085201"]
    }

    private func statusBody() -> [String: Any] {
        ["deviceList": [["wifiId": wifiId, "deviceId": deviceId]]]
    }

    private enum CmdOutcome { case ok, fail, okNoStatus }

    private func postCommand(url: String, body: [String: Any], statusRequired: Bool) async throws -> CmdOutcome {
        let data = try JSONSerialization.data(withJSONObject: body)
        let result = try await http.postJSON(url: url, headers: headers, body: data)
        guard let root = result as? [String: Any],
              let response = root["response"] as? [String: Any],
              (response["resultCode"] as? Int) == 0 || (response["resultCode"] as? NSNumber)?.intValue == 0
        else { return .fail }
        do {
            let parsed = try HisenseCloud.parseStatusCSV(try HisenseCloud.extractStatusPayload(root))
            status.merge(parsed) { _, n in n }
            return .ok
        } catch {
            return statusRequired ? .fail : .okNoStatus
        }
    }

    private func withRefresh(url: () -> String, body: [String: Any], statusRequired: Bool) async throws -> CmdOutcome {
        let first = try await postCommand(url: url(), body: body, statusRequired: statusRequired)
        if first != .fail { return first }
        NSLog("[Hisense] token expired; refreshing")
        accessToken = try await refresher.refreshAccessToken(refreshToken: refreshToken)
        return try await postCommand(url: url(), body: body, statusRequired: statusRequired)
    }

    private func sendAndRefreshStatus(url: () -> String, body: [String: Any]) async throws -> Bool {
        let outcome = try await withRefresh(url: url, body: body, statusRequired: false)
        if outcome == .ok { return true }
        if outcome == .okNoStatus {
            return try await checkStatus() != nil
        }
        return false
    }

    func turnOn() async throws -> Bool {
        var body = powerBody()
        body["attributes"] = "{\"onAndOff\":\"On\"}"
        return try await sendAndRefreshStatus(url: powerURL, body: body)
    }

    func turnOff() async throws -> Bool {
        var body = powerBody()
        body["attributes"] = "{\"onAndOff\":\"Off\"}"
        return try await sendAndRefreshStatus(url: powerURL, body: body)
    }

    func sendLogicCommand(cmdId: Int, param: Int) async throws -> Bool {
        var body = commandBody()
        body["cmdList"] = [
            ["cmdId": cmdId, "cmdOrder": 0, "cmdParm": param, "delayTime": 0],
        ]
        return try await sendAndRefreshStatus(url: commandURL, body: body)
    }

    func checkStatus() async throws -> [String: Any]? {
        let outcome = try await withRefresh(url: statusURL, body: statusBody(), statusRequired: true)
        return outcome == .ok ? status : nil
    }
}
