import Foundation

/// Result surfaced to Edge UI / AppModel — no Controller types required by callers.
struct GoProPluginResult {
    let ok: Bool
    let message: String
    let localPath: String?
    /// `latest_photo` found a local cache; UI may prompt before force redownload.
    let alreadyCached: Bool
    let cachedName: String?
    let cachedTimestamp: String?

    static func success(
        _ message: String,
        localPath: String? = nil,
        alreadyCached: Bool = false,
        cachedName: String? = nil,
        cachedTimestamp: String? = nil
    ) -> GoProPluginResult {
        GoProPluginResult(
            ok: true,
            message: message,
            localPath: localPath,
            alreadyCached: alreadyCached,
            cachedName: cachedName,
            cachedTimestamp: cachedTimestamp
        )
    }

    static func failure(_ message: String) -> GoProPluginResult {
        GoProPluginResult(
            ok: false,
            message: message,
            localPath: nil,
            alreadyCached: false,
            cachedName: nil,
            cachedTimestamp: nil
        )
    }
}

/// Plugin entry (manifest `entry.ios`). Edge UI / command routing talk only to this type.
final class GoProPluginEntry {
    static let skillId = GoProSkill.skillId

    private let controller: GoProController
    private let skill: GoProSkill

    init(controller: GoProController = GoProController(driver: GoProDriver())) {
        self.controller = controller
        self.skill = GoProSkill(controller: controller)
    }

    var statusSummary: String { controller.lastStatusSummary }
    var lastPhotoLocalPath: String? { controller.lastPhotoLocalPath }
    var lastPhotoData: Data? { controller.lastPhotoData }

    /// Forward pipeline progress (e.g. wait-for-Wi‑Fi) to the host app.
    var onProgress: ((String) -> Void)? {
        get { controller.onProgress }
        set { controller.onProgress = newValue }
    }

    func makeCapabilityPlugin() -> CapabilityPlugin {
        CameraCaptureCapabilityPlugin(controller: controller)
    }

    /// Device-command dispatch for CommandController (no GoProController leak to App).
    func handleDeviceCommand(action: String, command: [String: Any] = [:]) async -> ControllerResult {
        await controller.executeCommand(action: action, command: command)
    }

    /// UI / host invoke surface — actions mirror skill (+ `join_wifi`).
    func invoke(action: String, params: [String: String] = [:]) async -> GoProPluginResult {
        let normalized = action.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalized {
        case "join_wifi", "join_camera_wifi":
            let ssid = params["ssid"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !ssid.isEmpty else {
                return .failure("请填写 SSID")
            }
            let password = params["password"]
            let result = await controller.joinCameraWiFi(
                ssid: ssid,
                password: (password?.isEmpty == false) ? password : nil
            )
            return result.ok ? .success(result.message) : .failure(result.message)

        case "latest_photo":
            let forceRaw = params["force"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
            let force = forceRaw == "true" || forceRaw == "1" || forceRaw == "yes"
            let fetch = await controller.fetchLatestPhoto(forceRedownload: force)
            switch fetch {
            case let .alreadyDownloaded(item, localPath):
                return .success(
                    "已缓存 \(item.name) ts=\(item.timestamp) · 等待确认是否重下",
                    localPath: localPath,
                    alreadyCached: true,
                    cachedName: item.name,
                    cachedTimestamp: item.timestamp.isEmpty ? "未知" : item.timestamp
                )
            case let .downloaded(r):
                return r.ok
                    ? .success(r.message, localPath: controller.lastPhotoLocalPath)
                    : .failure(r.message)
            case let .failed(message):
                return .failure(message)
            }

        default:
            let ctx = SkillContext(edgeId: "local", planId: "ui", stepId: "1")
            let skillResult = await skill.execute(capabilityId: normalized, params: params, context: ctx)
            let path: String?
            switch normalized {
            case "download_latest_from_server", "upload_photo", "latest_photo",
                 "capture_photo", "take_photo", Capabilities.cameraCapture:
                path = controller.lastPhotoLocalPath
            default:
                path = nil
            }
            if skillResult.ok {
                return .success(skillResult.message ?? "ok", localPath: path)
            }
            return .failure(skillResult.message ?? "failed")
        }
    }
}
