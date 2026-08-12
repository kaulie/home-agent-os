import Foundation
import Combine

struct GoProActionEvent: Identifiable, Equatable {
    let id: UUID
    let timestamp: Date
    let ok: Bool
    let body: String

    init(id: UUID = UUID(), timestamp: Date = Date(), ok: Bool, body: String) {
        self.id = id
        self.timestamp = timestamp
        self.ok = ok
        self.body = body
    }

    var timeText: String {
        Self.formatter.string(from: timestamp)
    }

    var resultText: String { ok ? "成功" : "失败" }

    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()
}

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    static let preferredEdgeId = "living-room-iphone"
    /// Brain-issued id when available; otherwise local client hint.
    var edgeId: String { edgeAgent.assignedEdgeId ?? Self.preferredEdgeId }
    static let edgeIdentity = EdgeIdentity(
        edgeId: preferredEdgeId,
        displayName: "客厅 · iPhone Edge",
        deviceType: .iphone,
        room: "living-room",
        appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
    )

    let brain = MockBrainClient()
    let skillRegistry = SkillRegistry()
    let capabilityRegistry = CapabilityRegistry()
    let edgeAgent: EdgeAgent
    let goproPlugin: GoProPluginEntry
    let intentController: IntentController
    let intentJourney: IntentJourneyStore
    /// Mirrored from `intentJourney` so SwiftUI reliably refreshes (nested ObservableObject).
    @Published private(set) var activeIntentJourney: IntentJourney?
    let commandController: CommandController
    let commandSource: HttpCommandSource
    let commandHandler: CommandHandler
    let edgeReporter: HttpEdgeReporter
    let capabilityRegisterController: CapabilityRegisterController

    /// Last edge-info snapshot acknowledged by local brain (and attempted HTTP report).
    @Published var lastEdgeInfo: EdgeNodeInfo?

    /// Single-shot response boxes (only updated by manual action buttons).
    @Published var statusApiResponse: String = ""
    @Published var captureApiResponse: String = ""
    @Published var latestApiResponse: String = ""
    @Published var uploadApiResponse: String = ""
    @Published var serverDownloadApiResponse: String = ""
    @Published var intentApiResponse: String = ""
    @Published var commandPullApiResponse: String = ""
    @Published var commandExecuteApiResponse: String = ""
    @Published var capabilityRegisterApiResponse: String = ""
    @Published var edgeRegisterApiResponse: String = ""
    @Published var edgeHeartbeatApiResponse: String = ""
    /// Editable buffer for pulled commands JSON (filled by pull, consumed by execute).
    @Published var commandsText: String = ""
    /// Append-only pull history for UI (newest first); does not replace [commandsText].
    @Published var commandsPullHistory: String = ""
    /// Local file path of last successful GoPro `latest_photo` (camera download preview).
    @Published var latestPhotoPath: String?
    /// Local file path of last successful download from business server (separate from GoPro).
    @Published var serverPhotoPath: String?
    @Published var goproCurrentStatus: String = "暂时未知"
    /// Wall-clock time of last successful status parse (shown next to current status).
    @Published var goproStatusUpdatedAt: Date?

    var goproStatusTimeSuffix: String {
        guard let goproStatusUpdatedAt else { return "" }
        return "（\(Self.statusTimeFormatter.string(from: goproStatusUpdatedAt))）"
    }

    private static let statusTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private static let pullTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    /// Per-panel execution history (manual + scheduled).
    @Published var statusEvents: [GoProActionEvent] = []
    @Published var captureEvents: [GoProActionEvent] = []
    @Published var latestEvents: [GoProActionEvent] = []
    @Published var uploadEvents: [GoProActionEvent] = []
    @Published var serverDownloadEvents: [GoProActionEvent] = []
    @Published var intentEvents: [GoProActionEvent] = []
    @Published var commandPullEvents: [GoProActionEvent] = []
    @Published var commandExecuteEvents: [GoProActionEvent] = []

    /// planId → (actionName, updateSingleShotBox)
    var pendingPlans: [String: (action: String, updateSnapshot: Bool)] = [:]

    /// Default upload endpoint (cloud / Brain photo API; cellular OK after leaving GoPro AP).
    nonisolated static let defaultUploadURL = "http://115.190.153.53:9527/api/v1/photos/upload"
    /// Default download-latest endpoint on the same host.
    nonisolated static let defaultServerDownloadURL = "http://115.190.153.53:9527/api/v1/photos/download_latest"
    /// Debug cast sample on cloud static host (`server/photo_upload_*.py` public URL shape).
    nonisolated static let defaultCastPhotoURL =
        "http://115.190.153.53:8080/5618e662_1786162947_GOPR0945.JPG"
    /// Default intent POST endpoint.
    nonisolated static let defaultIntentURL = "http://115.190.153.53:9527/api/v1/intent"
    /// Default intent detail poll endpoint (derived at runtime from Intent URL).
    nonisolated static let defaultIntentDetailURL = "http://115.190.153.53:9527/api/v1/intent_detail"
    /// Default queued-intents pull endpoint.
    /// Do not pin `intent_status=intent_parsed`: after scheduler reports
    /// `intent_dispatched`, the executor still needs to pull the same intent.
    nonisolated static let defaultCommandsPullURL =
        "http://115.190.153.53:9527/api/v1/devices/living-room/intents"
    /// Business server base for edge register / heartbeat.
    nonisolated static let defaultEdgeReportBaseURL = "http://115.190.153.53:9527"
    /// Edge node first-contact register (Brain issues edgeId).
    nonisolated static let defaultEdgeRegisterURL = "http://115.190.153.53:9527/api/v1/edge-register"
    /// Edge node heartbeat (requires Brain-issued edgeId).
    nonisolated static let defaultEdgeHeartbeatURL = "http://115.190.153.53:9527/api/v1/edge-heartbeat"
    /// Debug: POST selected capabilities/skills mirror (legacy).
    nonisolated static let defaultCapabilityRegisterURL =
        "http://115.190.153.53:9527/api/v1/edges/living-room-iphone/capabilities"

    private var cancellables = Set<AnyCancellable>()

    private init() {
        goproPlugin = GoProPluginEntry()
        intentController = IntentController()
        intentJourney = IntentJourneyStore()
        intentController.journeyStore = intentJourney
        commandController = CommandController(gopro: goproPlugin)
        capabilityRegisterController = CapabilityRegisterController()
        edgeReporter = HttpEdgeReporter(baseURL: Self.defaultEdgeReportBaseURL, enabled: true)
        let composite = CompositeBrainClient(local: brain, remote: edgeReporter)
        commandSource = HttpCommandSource(pullURL: Self.defaultCommandsPullURL)
        let localRuntime = LocalEdgeRuntime(
            edgeId: Self.preferredEdgeId,
            registry: skillRegistry,
            brain: composite,
            intentController: intentController
        )
        let localNode = EdgeRuntimeNode(
            nodeId: Self.preferredEdgeId,
            displayName: Self.edgeIdentity.displayName
        )
        commandHandler = CommandHandler(
            dispatcher: LocalTaskDispatcher(runtime: localRuntime),
            localNode: localNode,
            intentController: intentController
        )
        edgeAgent = EdgeAgent(
            identity: Self.edgeIdentity,
            brain: composite,
            capabilityRegistry: capabilityRegistry,
            skillRegistry: skillRegistry,
            heartbeatIntervalMs: 15_000,
            commandSource: commandSource,
            commandHandler: commandHandler,
            localRuntime: localRuntime,
            intentController: intentController
        )
        commandController.commandHandler = commandHandler
        edgeAgent.healthProvider = self
        // Device plugins: Cast stays installed locally for UI/debug; Brain advertise
        // is gated by EdgeAgent.advertiseChromecastDisplayToBrain (currently off).
        edgeAgent.installCapabilities([
            goproPlugin.makeCapabilityPlugin(),
            ChromecastPluginEntry().makeCapabilityPlugin(),
        ])
        // Local debug plans (intent.dispatch / commands.pull) — not advertised to Brain.
        edgeAgent.installSkills([
            IntentSkill(controller: intentController),
            CommandSkill(controller: commandController),
        ])
        // Mirror nested store → @Published so ContentView always redraws the timeline.
        intentJourney.$activeJourney
            .receive(on: RunLoop.main)
            .sink { [weak self] journey in
                self?.activeIntentJourney = journey
            }
            .store(in: &cancellables)

        // After all stored properties are initialized (cannot capture self earlier).
        goproPlugin.onProgress = { [weak self] message in
            Task { @MainActor in
                guard let self else { return }
                self.goproCurrentStatus = message
                self.goproStatusUpdatedAt = Date()
                if let journey = self.intentJourney.activeJourney {
                    self.intentJourney.updatePlanStep(
                        intentId: journey.jobId,
                        capability: Capabilities.cameraCapture,
                        status: .running,
                        detail: message
                    )
                }
                if message.contains("wait_wifi") || message.contains("Wi‑Fi") || message.contains("Wi-Fi") {
                    self.captureApiResponse = message
                }
            }
        }
    }

    /// Run a GoPro plugin action via Entry (UI path — no Controller/Driver).
    @discardableResult
    func performGoPro(
        action: String,
        params: [String: String] = [:],
        updateSnapshot: Bool = true
    ) async -> GoProPluginResult {
        let result = await goproPlugin.invoke(action: action, params: params)
        applyGoProResult(action: action, result: result, updateSnapshot: updateSnapshot)
        return result
    }

    func applyGoProResult(action: String, result: GoProPluginResult, updateSnapshot: Bool) {
        let event = GoProActionEvent(ok: result.ok, body: result.message)
        switch action {
        case "status":
            statusEvents.insert(event, at: 0)
            if statusEvents.count > 100 { statusEvents = Array(statusEvents.prefix(100)) }
            if updateSnapshot { statusApiResponse = result.message }
            if result.ok {
                goproCurrentStatus = goproPlugin.statusSummary
                goproStatusUpdatedAt = Date()
            }
        case "capture_photo", "capture":
            captureEvents.insert(event, at: 0)
            if captureEvents.count > 100 { captureEvents = Array(captureEvents.prefix(100)) }
            if updateSnapshot { captureApiResponse = result.message }
            if !goproPlugin.statusSummary.isEmpty, goproPlugin.statusSummary != "暂时未知" {
                goproCurrentStatus = goproPlugin.statusSummary
                goproStatusUpdatedAt = Date()
            }
        case "latest_photo":
            if result.alreadyCached {
                // UI handles confirmation dialog; do not treat as final download yet.
                if updateSnapshot { latestApiResponse = result.message }
                return
            }
            latestEvents.insert(event, at: 0)
            if latestEvents.count > 100 { latestEvents = Array(latestEvents.prefix(100)) }
            if updateSnapshot {
                latestApiResponse = result.message
                if result.ok {
                    latestPhotoPath = result.localPath ?? goproPlugin.lastPhotoLocalPath
                }
            }
        case "upload_photo":
            uploadEvents.insert(event, at: 0)
            if uploadEvents.count > 100 { uploadEvents = Array(uploadEvents.prefix(100)) }
            if updateSnapshot { uploadApiResponse = result.message }
        case "download_latest_from_server":
            serverDownloadEvents.insert(event, at: 0)
            if serverDownloadEvents.count > 100 {
                serverDownloadEvents = Array(serverDownloadEvents.prefix(100))
            }
            if updateSnapshot {
                serverDownloadApiResponse = result.message
                if result.ok {
                    serverPhotoPath = result.localPath ?? goproPlugin.lastPhotoLocalPath
                }
            }
        default:
            break
        }
    }

    func currentEdgeHealth() -> EdgeHealthSnapshot {
        var details: [String: String] = [
            "agent": edgeAgent.running ? "running" : "stopped",
            "services": "\(skillRegistry.services().count)",
            "capabilities": "\(skillRegistry.services().reduce(0) { $0 + $1.capabilities.count })",
        ]
        details["gopro"] = goproCurrentStatus
        if let goproStatusUpdatedAt {
            details["gopro_updated_at"] = Self.statusTimeFormatter.string(from: goproStatusUpdatedAt)
        }

        let status: EdgeHealthStatus
        let summary: String
        if !edgeAgent.running {
            status = .unknown
            summary = "agent not running"
        } else if goproCurrentStatus.contains("失败") || goproCurrentStatus.lowercased().contains("error") {
            status = .degraded
            summary = "agent running; GoPro degraded"
        } else {
            status = .healthy
            summary = "agent running"
        }
        return EdgeHealthSnapshot(status: status, summary: summary, details: details)
    }

    func routeReport(planId: String, ok: Bool, message: String) {
        guard let pending = pendingPlans.removeValue(forKey: planId) else { return }
        let event = GoProActionEvent(ok: ok, body: message)
        switch pending.action {
        case "status":
            statusEvents.insert(event, at: 0)
            if statusEvents.count > 100 { statusEvents = Array(statusEvents.prefix(100)) }
            if pending.updateSnapshot { statusApiResponse = message }
            if ok {
                goproCurrentStatus = goproPlugin.statusSummary
                goproStatusUpdatedAt = Date()
            }
        case "capture_photo", "capture":
            captureEvents.insert(event, at: 0)
            if captureEvents.count > 100 { captureEvents = Array(captureEvents.prefix(100)) }
            if pending.updateSnapshot { captureApiResponse = message }
            // Capture may refresh lastStatusSummary
            if !goproPlugin.statusSummary.isEmpty,
               goproPlugin.statusSummary != "暂时未知" {
                goproCurrentStatus = goproPlugin.statusSummary
                goproStatusUpdatedAt = Date()
            }
        case "latest_photo":
            latestEvents.insert(event, at: 0)
            if latestEvents.count > 100 { latestEvents = Array(latestEvents.prefix(100)) }
            if pending.updateSnapshot {
                latestApiResponse = message
                if ok {
                    latestPhotoPath = goproPlugin.lastPhotoLocalPath
                }
            }
        case "upload_photo":
            uploadEvents.insert(event, at: 0)
            if uploadEvents.count > 100 { uploadEvents = Array(uploadEvents.prefix(100)) }
            if pending.updateSnapshot { uploadApiResponse = message }
        case "download_latest_from_server":
            serverDownloadEvents.insert(event, at: 0)
            if serverDownloadEvents.count > 100 {
                serverDownloadEvents = Array(serverDownloadEvents.prefix(100))
            }
            if pending.updateSnapshot {
                serverDownloadApiResponse = message
                if ok {
                    serverPhotoPath = goproPlugin.lastPhotoLocalPath
                }
            }
        case "dispatch":
            intentEvents.insert(event, at: 0)
            if intentEvents.count > 100 { intentEvents = Array(intentEvents.prefix(100)) }
            if pending.updateSnapshot { intentApiResponse = message }
            // Backup path: apply journey even if IntentController store wiring missed.
            if ok {
                if let snapshot = IntentJobSnapshot.parse(jsonText: message) {
                    intentJourney.startFromPost(snapshot)
                    let url = intentController.lastServerURL
                    intentJourney.startPolling(jobId: snapshot.jobId) { [weak self] jobId in
                        await self?.intentController.fetchJob(jobId: jobId, intentURL: url)
                    }
                } else if IntentJobSnapshot.isSuccessWithoutIntentId(message) {
                    intentJourney.markLegacyServerMissingJob(
                        detail: "服务端未返回 intent_id。"
                    )
                }
            } else if activeIntentJourney != nil {
                intentJourney.markLegacyServerMissingJob(
                    detail: message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? "指令下发失败"
                        : String(message.prefix(200))
                )
            }
        case "pull":
            commandPullEvents.insert(event, at: 0)
            if commandPullEvents.count > 100 { commandPullEvents = Array(commandPullEvents.prefix(100)) }
            if pending.updateSnapshot {
                commandPullApiResponse = message
                if ok {
                    let body = Self.stripTimingSuffix(message)
                    commandsText = body
                    let stamp = Self.pullTimeFormatter.string(from: Date())
                    let block = "════ \(stamp) ════\n\(body)"
                    if commandsPullHistory.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        commandsPullHistory = block
                    } else {
                        commandsPullHistory = block + "\n\n" + commandsPullHistory
                    }
                    if commandsPullHistory.count > 80_000 {
                        commandsPullHistory =
                            String(commandsPullHistory.prefix(80_000)) + "\n…(older truncated)"
                    }
                }
            }
        case "execute":
            commandExecuteEvents.insert(event, at: 0)
            if commandExecuteEvents.count > 100 {
                commandExecuteEvents = Array(commandExecuteEvents.prefix(100))
            }
            if pending.updateSnapshot { commandExecuteApiResponse = message }
            if !goproPlugin.statusSummary.isEmpty,
               goproPlugin.statusSummary != "暂时未知" {
                goproCurrentStatus = goproPlugin.statusSummary
                goproStatusUpdatedAt = Date()
            }
        default:
            break
        }
    }

    private static func stripTimingSuffix(_ text: String) -> String {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard let last = lines.last, last.hasPrefix("⏱") else { return text }
        return lines.dropLast().joined(separator: "\n")
    }
}

extension AppModel: EdgeHealthProviding {}
