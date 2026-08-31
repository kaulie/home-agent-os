import Combine
import Foundation
import Network
import UIKit
import UniformTypeIdentifiers

/// Upload state of a locally captured photo. Capture success is acknowledged the
/// moment the photo lands in the local list; this tracks only the background upload.
enum LocalMediaUploadStatus: String, Codable, Equatable {
    /// Saved locally, waiting for the background upload to start.
    case pending
    /// Background upload in flight (never persisted across relaunch; see load).
    case uploading
    /// Upload done; `inputAssetId` holds the real Brain asset_id.
    case uploaded
    /// Upload failed; photo stays in the local list and can be retried.
    case failed
}

struct ChatTurn: Identifiable, Equatable {
    let id: UUID
    var intentId: String
    var createdAt: Date
    var userText: String
    var source: String
    var journey: IntentJourney
    var assistantText: String?
    var awaitingTerminal: Bool
    /// Visual Input asset (optional). iPhone photos carry a `ph_…` local id until uploaded.
    var inputAssetId: String? = nil
    /// Per-item background upload state (iphone.photo; document.scan is always uploaded when listed).
    var uploadStatus: LocalMediaUploadStatus? = nil

    var isDocumentScan: Bool { source == "document.scan" }
    var isIPhonePhoto: Bool { source == "iphone.photo" }
    var isIPhoneFile: Bool { source == "iphone.file" }
    var isIPhoneAudio: Bool { source == "iphone.audio" }
    var isLocalMedia: Bool { isDocumentScan || isIPhonePhoto || isIPhoneFile || isIPhoneAudio }

    static func isBrainIntentId(_ raw: String) -> Bool {
        Int(raw.trimmingCharacters(in: .whitespacesAndNewlines)) != nil
    }

    static func fromHistory(_ snapshot: IntentJobSnapshot) -> ChatTurn {
        let journey = IntentJourney.hydrated(from: snapshot)
        return ChatTurn(
            id: UUID(),
            intentId: snapshot.jobId,
            createdAt: snapshot.createdAt ?? Date(),
            userText: snapshot.text,
            source: snapshot.source,
            journey: journey,
            assistantText: ChatTurn.assistantText(for: journey),
            awaitingTerminal: !snapshot.wireStatus.isTerminal
        )
    }

    static func assistantText(for journey: IntentJourney) -> String {
        if journey.timedOut, !journey.terminal {
            let err = journey.error?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return err.isEmpty ? "等待超时，服务端尚未到达终态" : err
        }
        if journey.current == .failed {
            let err = journey.error?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return err.isEmpty ? "意图失败" : err
        }
        if let pres = journey.presentation, pres.type == .text || pres.type == .html, !pres.text.isEmpty {
            return pres.text
        }
        return ""
    }
}

private enum ChatPersistence {
    private static let key = "livingroom.chatTurns.v1"
    private static let maxTurns = 80

    struct Record: Codable {
        var intentId: String
        var createdAt: Date
        var userText: String
        var source: String
        var assistantText: String?
        var awaitingTerminal: Bool
        var inputAssetId: String?
        var uploadStatus: String?
    }

    static func load() -> [ChatTurn] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let rows = try? JSONDecoder().decode([Record].self, from: data) else {
            return []
        }
        return rows.compactMap { row in
            let text = row.userText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return nil }
            let intentId = row.intentId.trimmingCharacters(in: .whitespacesAndNewlines)
            let source = normalizedSource(row.source)
            if source == "document.scan" || source == "iphone.photo" || source == "iphone.file"
                || source == "iphone.audio" {
                let aid = (row.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !aid.isEmpty else { return nil }
                let prefix: String
                switch source {
                case "iphone.photo": prefix = "photo"
                case "iphone.file": prefix = "file"
                case "iphone.audio": prefix = "audio"
                default: prefix = "scan"
                }
                let jobId = intentId.isEmpty ? "\(prefix)-\(aid)" : intentId
                return ChatTurn(
                    id: UUID(),
                    intentId: jobId,
                    createdAt: row.createdAt,
                    userText: text,
                    source: source,
                    journey: IntentJourney.make(jobId: jobId, text: text, status: .succeeded),
                    assistantText: row.assistantText,
                    awaitingTerminal: false,
                    inputAssetId: aid,
                    uploadStatus: restoredUploadStatus(source: source, raw: row.uploadStatus, assetId: aid)
                )
            }
            guard !intentId.isEmpty, intentId != "pending…" else { return nil }
            let journey: IntentJourney = {
                if ChatTurn.isBrainIntentId(intentId),
                   let cached = IntentDetailCache.snapshot(for: intentId) {
                    return IntentJourney.hydrated(from: cached)
                }
                let status: IntentPhase = row.awaitingTerminal ? .running : .succeeded
                return JourneyLocalCache.enrich(
                    IntentJourney.make(jobId: intentId, text: text, status: status)
                )
            }()
            var restored = journey
            if restored.clientStartedAt == nil {
                restored.clientStartedAt = row.createdAt
            }
            // Finished turns without a stored t1 stay without clientFinishedAt (show "—").
            if row.awaitingTerminal {
                restored.clientFinishedAt = nil
            }
            return ChatTurn(
                id: UUID(),
                intentId: intentId,
                createdAt: row.createdAt,
                userText: text,
                source: source,
                journey: restored,
                assistantText: row.assistantText,
                awaitingTerminal: row.awaitingTerminal,
                inputAssetId: row.inputAssetId
            )
        }
    }

    static func save(_ turns: [ChatTurn]) {
        let rows: [Record] = turns.suffix(maxTurns).compactMap { turn in
            if turn.isLocalMedia {
                let aid = (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !aid.isEmpty else { return nil }
                let intentId = turn.intentId.trimmingCharacters(in: .whitespacesAndNewlines)
                let prefix: String
                if turn.isIPhonePhoto {
                    prefix = "photo"
                } else if turn.isIPhoneFile {
                    prefix = "file"
                } else if turn.isIPhoneAudio {
                    prefix = "audio"
                } else {
                    prefix = "scan"
                }
                return Record(
                    intentId: intentId.isEmpty ? "\(prefix)-\(aid)" : intentId,
                    createdAt: turn.createdAt,
                    userText: turn.userText,
                    source: turn.source,
                    assistantText: turn.assistantText,
                    awaitingTerminal: false,
                    inputAssetId: aid,
                    uploadStatus: turn.isIPhonePhoto && turn.uploadStatus == .uploading
                        ? LocalMediaUploadStatus.pending.rawValue
                        : turn.uploadStatus?.rawValue
                )
            }
            let intentId = turn.intentId.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !intentId.isEmpty, intentId != "pending…" else { return nil }
            return Record(
                intentId: intentId,
                createdAt: turn.createdAt,
                userText: turn.userText,
                source: turn.source,
                assistantText: turn.assistantText,
                awaitingTerminal: turn.awaitingTerminal,
                inputAssetId: turn.inputAssetId,
                uploadStatus: nil
            )
        }
        if let data = try? JSONEncoder().encode(rows) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: key)
        IntentDetailCache.clear()
        JourneyLocalCache.clear()
    }

    /// iphone.photo and document.scan carry upload state. `uploading` never survives a
    /// relaunch (no upload is in flight), so photos come back as `pending` and the
    /// bootstrap re-queues them. Records written before this field existed derive
    /// from the id shape: local `ph_…` id → still pending, real asset_id → uploaded.
    /// Scan rows in the list always finished upload before being shown.
    private static func restoredUploadStatus(source: String, raw: String?, assetId: String) -> LocalMediaUploadStatus? {
        switch source {
        case "document.scan":
            if let raw, let value = LocalMediaUploadStatus(rawValue: raw), value != .uploading {
                return value
            }
            return .uploaded
        case "iphone.photo":
            if let raw, let value = LocalMediaUploadStatus(rawValue: raw) {
                return value == .uploading ? .pending : value
            }
            return LocalPhotoStore.isLocalId(assetId) ? .pending : .uploaded
        default:
            return nil
        }
    }

    private static func normalizedSource(_ raw: String) -> String {
        switch raw {
        case "voice": return "voice"
        case "document.scan": return "document.scan"
        case "iphone.photo": return "iphone.photo"
        case "iphone.file": return "iphone.file"
        case "iphone.audio": return "iphone.audio"
        case "visual": return "visual"
        default: return "text"
        }
    }
}

/// P0 dual-Brain: per-Brain heartbeat state so the app can show two distinguishable
/// heartbeat records (LAN + Cloud) instead of one merged view.
enum HeartbeatPhase: Equatable {
    case idle
    case sending
    case retrying(attempt: Int)

    var isActive: Bool {
        switch self {
        case .idle: return false
        case .sending, .retrying: return true
        }
    }

    var rowLabel: String? {
        switch self {
        case .idle: return nil
        case .sending: return "发送中"
        case .retrying(let n): return "重试 \(n)/3"
        }
    }
}

struct BrainHeartbeatStatus: Equatable {
    let mode: BrainEndpoint.Mode
    var registered: Bool = false
    var registeredAt: Date?
    var lastAttemptAt: Date?
    var lastSuccessAt: Date?
    var lastOk: Bool = false
    var lastError: String = ""
    var phase: HeartbeatPhase = .idle

    var hasAttempted: Bool { lastAttemptAt != nil }
}

/// What the settings「自动发现」button managed to resolve over mDNS.
struct MdnsDiscoverOutcome {
    var brainFound = false
    var brainURL = ""
    var brainMdns = ""
    var gatewayFound = false
    var gatewayURL = ""
    var gatewayMdns = ""
}

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()
    static let defaultIntentURL = BrainEndpoint.defaultLanIntentURL
    static let defaultLanBrainURL = BrainEndpoint.defaultLanBase
    static let defaultCloudBrainURL = BrainEndpoint.defaultCloudBase

    let intentClient = IntentClient()
    let intentJourney = IntentJourneyStore()

    /// Resolved Brain actually used for register / heartbeat / intent (LAN or Cloud).
    @Published private(set) var intentServerURL = BrainEndpoint.cloudIntentURL
    @Published var lanBrainURL = BrainEndpoint.lanBaseURL {
        didSet {
            let next = BrainEndpoint.normalizeBase(lanBrainURL)
            if next != lanBrainURL {
                lanBrainURL = next
                return
            }
            BrainEndpoint.lanBaseURL = next
        }
    }
    /// IPv4 Brain base after mDNS / probe (`http://x.x.x.x:9527`). Empty = not found yet.
    @Published var lanResolvedBase = BrainEndpoint.lanResolvedBaseURL {
        didSet {
            let next = BrainEndpoint.normalizeBase(lanResolvedBase)
            if next != lanResolvedBase {
                lanResolvedBase = next
                return
            }
            BrainEndpoint.lanResolvedBaseURL = next
        }
    }
    @Published var cloudBrainURL = BrainEndpoint.cloudBaseURL {
        didSet {
            let next = BrainEndpoint.normalizeBase(cloudBrainURL)
            if next != cloudBrainURL {
                cloudBrainURL = next
                return
            }
            BrainEndpoint.cloudBaseURL = next
        }
    }
    @Published var brainRouting: BrainEndpoint.Routing = BrainEndpoint.routing {
        didSet {
            guard brainRouting != oldValue else { return }
            BrainEndpoint.routing = brainRouting
            Task { await resolveBrainEndpoint(reregister: true) }
        }
    }
    @Published private(set) var brainEnvironment = BrainNetworkEnvironment()
    @Published private(set) var brainResolveBusy = false
    @Published private(set) var turns: [ChatTurn] = []
    @Published private(set) var activeIntentJourney: IntentJourney?
    @Published private(set) var lastResponse: String = ""
    @Published private(set) var sending = false
    @Published private(set) var participantId = ParticipantStore.participantId
    @Published private(set) var clientHint = ParticipantStore.clientHint
    @Published private(set) var historyNotice = ""
    @Published private(set) var skipScrollToLatest = false
    @Published private(set) var lastHeartbeatOk = ParticipantStore.lastHeartbeatAt != nil
    @Published private(set) var lastHeartbeatError = ""
    @Published private(set) var registeredAt = ParticipantStore.registeredAt
    /// P0 dual-Brain: per-Brain heartbeat status, shown as two distinguishable rows.
    @Published private(set) var lanHeartbeat = BrainHeartbeatStatus(mode: .lan)
    @Published private(set) var cloudHeartbeat = BrainHeartbeatStatus(mode: .cloud)
    /// Wall time of the most recent heartbeat *attempt* (success or fail).
    @Published private(set) var lastHeartbeatAt = ParticipantStore.lastHeartbeatAt
    /// Wall time of the most recent *successful* heartbeat (persisted).
    @Published private(set) var lastHeartbeatSuccessAt = ParticipantStore.lastHeartbeatAt
    @Published private(set) var enabledRoles = ParticipantStore.reportedRoles
    @Published private(set) var lastReportedRoles = ParticipantStore.lastReportedRoles
    /// P0 dual-Brain: last roles actually sent on a successful heartbeat, per Brain.
    @Published private(set) var lanLastReportedRoles = ParticipantStore.lastReportedRoles(for: .lan)
    @Published private(set) var cloudLastReportedRoles = ParticipantStore.lastReportedRoles(for: .cloud)
    @Published private(set) var nextHeartbeatAt: Date?
    @Published private(set) var clockSync: ClockSyncSample?
    @Published private(set) var clockSyncBusy = false
    @Published private(set) var clockSyncError = ""
    @Published private(set) var devBugBusyTurnIds: Set<UUID> = []
    @Published private(set) var devBugErrors: [UUID: String] = [:]
    @Published private(set) var scanBusy = false
    @Published private(set) var scanHint = ""
    @Published private(set) var photoHint = ""
    @Published private(set) var fileBusy = false
    @Published private(set) var fileHint = ""
    @Published private(set) var fileUploadingName = ""
    @Published private(set) var audioBusy = false
    @Published private(set) var audioHint = ""
    @Published var audioTitle = ""
    let audioRecorder = AudioRecorder()
    let audioPlayer = AudioPlayer()
    @Published var macIngestURL: String = UserDefaults.standard.string(forKey: "livingroom.macIngestURL") ?? "" {
        didSet { UserDefaults.standard.set(macIngestURL, forKey: "livingroom.macIngestURL") }
    }

    var conversationTurns: [ChatTurn] {
        turns.filter { !$0.isLocalMedia }
    }

    var scanTurns: [ChatTurn] {
        localMediaTurns(matching: { $0.isDocumentScan })
    }

    var photoTurns: [ChatTurn] {
        localMediaTurns(matching: { $0.isIPhonePhoto })
    }

    var fileTurns: [ChatTurn] {
        localMediaTurns(matching: { $0.isIPhoneFile })
    }

    var audioTurns: [ChatTurn] {
        localMediaTurns(matching: { $0.isIPhoneAudio })
    }

    func setScanHint(_ text: String) {
        scanHint = text
    }

    func setPhotoHint(_ text: String) {
        photoHint = text
    }

    func setFileHint(_ text: String) {
        fileHint = text
    }

    func setAudioHint(_ text: String) {
        audioHint = text
    }

    private func localMediaTurns(matching: (ChatTurn) -> Bool) -> [ChatTurn] {
        turns.filter { turn in
            guard matching(turn) else { return false }
            let aid = (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return !aid.isEmpty
        }
        .sorted { $0.createdAt > $1.createdAt }
    }

    private var historyNextBeforeId: Int?
    private var historyExhausted = false
    @Published private(set) var heartbeatBusy = false
    private var heartbeatLoop: Task<Void, Never>?
    private var lanBeatInFlight = false
    private var cloudBeatInFlight = false
    private var lanBeatPending = false
    private var cloudBeatPending = false
    /// Suppress duplicate foreground work while cold-start bootstrap is still running.
    private var coldBootstrapRunning = true
    private var pendingForegroundRefresh = false
    private var pendingPathResolve = false
    private var lanDiscoveryRetryTask: Task<Void, Never>?
    private var resolveWorkPending = false
    /// Keep ≤ Brain `ONLINE_TTL_SEC / 2` (TTL is 2× heartbeat).
    static let heartbeatIntervalSeconds: TimeInterval = 30
    static let heartbeatAttemptTimeout: TimeInterval = 3
    static let heartbeatMaxAttempts = 3
    static let heartbeatRetryGapSeconds: TimeInterval = 1
    /// Cap serial intent_detail refresh so a dead Brain cannot stall the UI for minutes.
    private static let maxStartupDetailRefresh = 8

    private var cancellables = Set<AnyCancellable>()
    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "livingroom.brain.path")

    private init() {
        ParticipantStore.applyGoProPreinstall()
        // P0: ensure a stable Runtime Identity exists before first register.
        ParticipantStore.ensureRuntimeId()
        enabledRoles = ParticipantStore.reportedRoles
        BrainEndpoint.migrateLanIdentityIfNeeded()
        lanBrainURL = BrainEndpoint.defaultLanBase
        BrainEndpoint.lanBaseURL = BrainEndpoint.defaultLanBase
        lanResolvedBase = BrainEndpoint.lanResolvedBaseURL
        cloudBrainURL = BrainEndpoint.cloudBaseURL
        brainRouting = BrainEndpoint.routing
        audioRecorder.objectWillChange
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
        audioPlayer.objectWillChange
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
        intentJourney.$activeJourney
            .receive(on: RunLoop.main)
            .sink { [weak self] journey in
                self?.activeIntentJourney = journey
            }
            .store(in: &cancellables)
        startPathMonitor()

        Task { @MainActor in
            MdnsDiscovery.logLaunchNetworkContext()
            DiscoveryDebugLog.shared.log("cold bootstrap start phase1 allowMdns=false allowLanProbe=false", category: "connect")
            // Let TabView / ContentView paint before sync load + network.
            await Task.yield()
            await Task.yield()
            turns = ChatPersistence.load()

            await resolveBrainEndpoint(reregister: false, allowMdns: false, allowLanProbe: false)
            DiscoveryDebugLog.shared.log("cold bootstrap phase1 done intentURL=\(intentServerURL)", category: "connect")
            let url = intentServerURL
            await ensureRegistered(serverURL: url, force: true)
            _ = await heartbeatNow(serverURL: url)
            enqueueBrainHeartbeat(mode: secondaryMode(for: url))
            startHeartbeatLoopIfNeeded()
            resumePendingPhotoUploads()

            async let history: Void = loadOlderHistory(serverURL: intentServerURL, silent: true)
            async let visible: Void = refreshVisibleTurns(serverURL: intentServerURL, onlyAwaiting: true)
            async let mdnsOutcome: MdnsDiscoverOutcome = refreshMdnsEndpoints()
            _ = await (history, visible, mdnsOutcome)

            DiscoveryDebugLog.shared.log("cold bootstrap phase2 allowMdns=true allowLanProbe=true", category: "connect")
            let baseline = url
            await resolveBrainEndpoint(reregister: true, allowMdns: true, allowLanProbe: true)
            let refreshed = intentServerURL
            if refreshed != baseline {
                DiscoveryDebugLog.shared.log("cold bootstrap phase2 switched \(baseline) → \(refreshed)", category: "connect")
                await ensureRegistered(serverURL: refreshed, force: true)
                _ = await heartbeatNow(serverURL: refreshed)
            }

            coldBootstrapRunning = false
            DiscoveryDebugLog.shared.log("cold bootstrap done intentURL=\(intentServerURL)", category: "connect")
            await flushPendingBrainRefreshWork()
        }
    }

    /// Run after bootstrap or when a refresh was skipped during cold start.
    private func flushPendingBrainRefreshWork() async {
        if pendingForegroundRefresh {
            pendingForegroundRefresh = false
            await performForegroundBrainRefresh()
            return
        }
        if pendingPathResolve {
            pendingPathResolve = false
            await resolveBrainEndpoint(reregister: true)
        }
        scheduleLanDiscoveryRetryIfNeeded()
    }

    /// If still on cloud while at home, retry LAN discovery once Bonjour has warmed up.
    private func scheduleLanDiscoveryRetryIfNeeded(delay: TimeInterval = 2.5) {
        lanDiscoveryRetryTask?.cancel()
        lanDiscoveryRetryTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard brainRouting != .cloud else {
                DiscoveryDebugLog.shared.log("LAN retry skipped: routing=cloud", category: "connect")
                return
            }
            guard brainEnvironment.looksOnHomeLAN else {
                DiscoveryDebugLog.shared.log("LAN retry skipped: not on home LAN", category: "connect")
                return
            }
            guard brainEnvironment.mode != .lan || brainEnvironment.lanProbeOk != true else {
                DiscoveryDebugLog.shared.log("LAN retry skipped: already on LAN with probe OK", category: "connect")
                return
            }
            DiscoveryDebugLog.shared.log("LAN retry scheduled (still on cloud at home)", category: "connect")
            let before = intentServerURL
            _ = await refreshMdnsEndpoints()
            await resolveBrainEndpoint(reregister: true)
            if intentServerURL != before {
                DiscoveryDebugLog.shared.log("LAN retry switched \(before) → \(intentServerURL)", category: "connect")
                await ensureRegistered(serverURL: intentServerURL, force: true)
                _ = await heartbeatNow(serverURL: intentServerURL)
            } else {
                DiscoveryDebugLog.shared.log("LAN retry unchanged url=\(intentServerURL)", category: "connect")
            }
        }
    }

    private func performForegroundBrainRefresh() async {
        DiscoveryDebugLog.shared.log("foreground refresh start", category: "connect")
        _ = await refreshMdnsEndpoints()
        await resolveBrainEndpoint(reregister: true)
        await catchUpHeartbeatIfOverdue()
        await refreshVisibleTurns(serverURL: intentServerURL, onlyAwaiting: true)
        resumePendingPhotoUploads()
        DiscoveryDebugLog.shared.log("foreground refresh done url=\(intentServerURL)", category: "connect")
    }

    /// Discover Brain / Gateway / img-server via mDNS and update the LAN slots so
    /// the app stops depending on a fixed LAN IP (IP changes are followed by mDNS).
    /// `force` (settings「自动发现」button) overwrites saved LAN slots and uses a
    /// longer browse timeout; cold start keeps a manual macIngest value unless it
    /// is still empty. Returns what was found so the button can show feedback.
    @discardableResult
    @MainActor
    func refreshMdnsEndpoints(force: Bool = false) async -> MdnsDiscoverOutcome {
        let timeout: TimeInterval = force ? 8 : 6
        DiscoveryDebugLog.shared.log(
            "refreshMdnsEndpoints force=\(force) timeout=\(timeout)s needGateway=\(force || macIngestURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)",
            category: "connect"
        )
        if force {
            // Rediscover Gateway independently. Keep last ping-verified Brain IP until a new Brain is found.
            DiscoveryDebugLog.shared.log("refreshMdnsEndpoints force: clearing macIngestURL only (keep lanResolvedBase until Brain hit)", category: "connect")
            macIngestURL = ""
        }
        let needGateway = force || macIngestURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty

        var brain: MdnsDiscovery.Endpoint?
        var gateway: MdnsDiscovery.Endpoint?

        await withTaskGroup(of: (Int, MdnsDiscovery.Endpoint?).self) { group in
            group.addTask {
                (0, await MdnsDiscovery.resolveBrainForAutoDiscover(mdnsTimeout: timeout))
            }
            if needGateway {
                group.addTask {
                    (1, await MdnsDiscovery.resolveGatewayForAutoDiscover(mdnsTimeout: timeout))
                }
            }
            for await (kind, ep) in group {
                if kind == 0 { brain = ep } else { gateway = ep }
            }
        }

        var outcome = MdnsDiscoverOutcome()
        if let brain {
            outcome.brainFound = true
            outcome.brainURL = brain.baseURL
            outcome.brainMdns = brain.mdnsBaseURL
            lanBrainURL = BrainEndpoint.defaultLanBase
            persistPingVerifiedLanBase(brain.baseURL)
        }
        if let gateway {
            outcome.gatewayFound = true
            outcome.gatewayURL = gateway.baseURL
            outcome.gatewayMdns = gateway.mdnsBaseURL
            macIngestURL = gateway.baseURL
        }
        DiscoveryDebugLog.shared.log(
            "refreshMdnsEndpoints outcome brain=\(outcome.brainFound ? outcome.brainURL : "—") gateway=\(outcome.gatewayFound ? outcome.gatewayURL : "—")",
            category: "connect"
        )
        return outcome
    }

    func onForeground() {
        Task { @MainActor in
            if coldBootstrapRunning {
                pendingForegroundRefresh = true
                return
            }
            await performForegroundBrainRefresh()
        }
    }

    func applyPinnedBrainURLs() async {
        BrainEndpoint.lanBaseURL = BrainEndpoint.defaultLanBase
        lanBrainURL = BrainEndpoint.defaultLanBase
        BrainEndpoint.lanResolvedBaseURL = lanResolvedBase
        BrainEndpoint.cloudBaseURL = cloudBrainURL
        BrainEndpoint.routing = brainRouting
        await resolveBrainEndpoint(reregister: true)
    }

    func predictedBrainMode(for routing: BrainEndpoint.Routing) -> BrainEndpoint.Mode {
        switch routing {
        case .lan: return .lan
        case .cloud: return .cloud
        case .auto:
            if brainEnvironment.lanProbeOk == true { return .lan }
            if brainEnvironment.lanProbeOk == false { return .cloud }
            return brainEnvironment.looksOnHomeLAN ? .lan : .cloud
        }
    }

    func predictedBrainBase(for routing: BrainEndpoint.Routing) -> String {
        predictedBrainMode(for: routing) == .lan
            ? BrainEndpoint.displayBase(from: lanConnectBase())
            : BrainEndpoint.displayBase(from: cloudBrainURL)
    }

    /// HTTP target for LAN Brain: resolved IPv4, never `brain.local` when an IP is known.
    func lanConnectBase() -> String {
        if BrainEndpoint.ipv4Host(from: lanResolvedBase) != nil {
            return BrainEndpoint.normalizeBase(lanResolvedBase)
        }
        if BrainEndpoint.ipv4Host(from: lanBrainURL) != nil {
            return BrainEndpoint.normalizeBase(lanBrainURL)
        }
        return BrainEndpoint.lanConnectBaseURL
    }

    /// Store only ping-verified IPv4. Never persist `brain.local`.
    private func persistPingVerifiedLanBase(_ raw: String) {
        let ipBase: String
        if let known = BrainEndpoint.ipv4Base(from: raw) {
            ipBase = known
        } else if let host = URL(string: BrainEndpoint.normalizeBase(raw))?.host,
                  let ip = MdnsDiscovery.resolveIPv4Host(host) {
            let port = URL(string: BrainEndpoint.normalizeBase(raw))?.port ?? 9527
            ipBase = "http://\(ip):\(port)"
        } else {
            return
        }
        if lanResolvedBase != ipBase {
            DiscoveryDebugLog.shared.log("persist ping-verified LAN \(ipBase)", category: "connect")
        }
        lanResolvedBase = ipBase
        BrainEndpoint.lanResolvedBaseURL = ipBase
        if let host = BrainEndpoint.ipv4Host(from: ipBase) {
            MdnsDiscovery.rememberBrainIP(host)
        }
    }

    private func lanCandidateBases() -> [String] {
        var bases: [String] = []
        func add(_ raw: String) {
            guard let ipBase = BrainEndpoint.ipv4Base(from: raw), !bases.contains(ipBase) else { return }
            bases.append(ipBase)
        }
        add(lanResolvedBase)
        add(lanBrainURL)
        for ip in MdnsDiscovery.rememberedBrainIPs() {
            add("http://\(ip):9527")
        }
        return bases
    }

    /// Probe known IPv4s in order; do not treat one timeout as “LAN is gone”.
    private func pingFirstReachableLan(bases: [String], timeout: TimeInterval) async -> (base: String, failDetail: String) {
        var lastFail = ""
        for base in bases {
            let intent = BrainEndpoint.intentURL(from: base)
            switch await intentClient.ping(serverURL: intent, clientSentAt: Date(), timeout: timeout) {
            case .ok:
                return (base, "")
            case let .failed(detail):
                lastFail = detail
                DiscoveryDebugLog.shared.log("LAN candidate ping FAIL \(intent): \(detail)", category: "connect")
            }
        }
        return ("", lastFail)
    }

    private func probeLanBrain(allowMdns: Bool) async -> (ok: Bool, detail: String) {
        let first = await pingFirstReachableLan(bases: lanCandidateBases(), timeout: 3)
        if !first.base.isEmpty {
            persistPingVerifiedLanBase(first.base)
            DiscoveryDebugLog.shared.log("LAN ping OK \(first.base)", category: "connect")
            return (true, "")
        }
        let kept = lanResolvedBase
        if allowMdns {
            if let brain = await MdnsDiscovery.resolveBrainForAutoDiscover(mdnsTimeout: 6) {
                lanBrainURL = BrainEndpoint.defaultLanBase
                let discovered = BrainEndpoint.normalizeBase(brain.baseURL)
                switch await intentClient.ping(
                    serverURL: BrainEndpoint.intentURL(from: discovered),
                    clientSentAt: Date(),
                    timeout: 3
                ) {
                case .ok:
                    persistPingVerifiedLanBase(discovered)
                    DiscoveryDebugLog.shared.log("LAN ping OK after rediscover \(discovered)", category: "connect")
                    return (true, "")
                case let .failed(detail):
                    DiscoveryDebugLog.shared.log("LAN rediscover ping FAIL \(discovered): \(detail)", category: "connect")
                    let retry = await pingFirstReachableLan(bases: lanCandidateBases(), timeout: 3)
                    if !retry.base.isEmpty {
                        persistPingVerifiedLanBase(retry.base)
                        DiscoveryDebugLog.shared.log("LAN ping OK other candidate \(retry.base)", category: "connect")
                        return (true, "")
                    }
                    if !kept.isEmpty {
                        DiscoveryDebugLog.shared.log(
                            "LAN probe failed; keeping last verified \(kept) (not dropping on one timeout)",
                            category: "connect"
                        )
                    }
                    return (false, detail)
                }
            }
        }
        if !kept.isEmpty {
            DiscoveryDebugLog.shared.log(
                "LAN probe failed; keeping last verified \(kept) (not dropping on one timeout)",
                category: "connect"
            )
        }
        return (false, first.failDetail.isEmpty ? "局域网 Brain 不可达" : first.failDetail)
    }

    /// 对时 ping succeeded: keep that IPv4 and, unless locked to cloud, actually use LAN.
    private func adoptLanFromSuccessfulPing() async {
        persistPingVerifiedLanBase(lanConnectBase())
        guard brainRouting != .cloud else { return }
        let next = BrainEndpoint.intentURL(from: lanConnectBase())
        let changed = next != intentServerURL
        intentServerURL = next
        intentClient.lastServerURL = next
        brainEnvironment.routing = brainRouting
        brainEnvironment.lanProbeOk = true
        brainEnvironment.lanProbeDetail = ""
        brainEnvironment.mode = .lan
        brainEnvironment.activeIntentURL = next
        DiscoveryDebugLog.shared.log("adopt LAN after 对时/ping url=\(next) changed=\(changed)", category: "connect")
        if changed, !coldBootstrapRunning {
            await ensureRegistered(serverURL: next, force: true)
        }
    }

    func applyBrainRouting(_ routing: BrainEndpoint.Routing) {
        let prev = brainRouting
        brainRouting = routing
        if prev != routing {
            DiscoveryDebugLog.shared.log("routing changed \(prev) → \(routing)", category: "connect")
        }
    }

    /// Auto: LAN when `/api/v1/ping` succeeds, else Cloud. Forced LAN / Cloud skip that choice.
    /// `allowMdns` / `allowLanProbe`: false during cold start so Bonjour / LAN ping do not block first frame.
    func resolveBrainEndpoint(
        reregister: Bool,
        allowMdns: Bool = true,
        allowLanProbe: Bool = true
    ) async {
        if brainResolveBusy {
            resolveWorkPending = true
            return
        }
        brainResolveBusy = true
        defer {
            brainResolveBusy = false
            if resolveWorkPending {
                resolveWorkPending = false
                Task { await self.resolveBrainEndpoint(reregister: true) }
            }
        }

        let routing = brainRouting
        DiscoveryDebugLog.shared.log(
            "resolveBrainEndpoint routing=\(routing) allowMdns=\(allowMdns) allowLanProbe=\(allowLanProbe) lanBase=\(lanConnectBase())",
            category: "connect"
        )
        let cloudIntent = BrainEndpoint.intentURL(from: cloudBrainURL)
        let looksLAN = brainEnvironment.looksOnHomeLAN
        var probeOk: Bool?
        var probeDetail = ""

        let shouldProbeLAN = allowLanProbe && routing != .cloud && (looksLAN || routing == .lan)
        if shouldProbeLAN {
            let probed = await probeLanBrain(allowMdns: allowMdns)
            probeOk = probed.ok
            probeDetail = probed.detail
        } else if routing == .cloud {
            probeOk = nil
            probeDetail = "已强制走云 Brain，跳过 LAN 探测"
        } else {
            probeOk = false
            probeDetail = "当前不是家庭局域网，跳过 LAN 探测"
        }

        let resolvedLanIntent = BrainEndpoint.intentURL(from: lanConnectBase())
        let useLAN: Bool
        switch routing {
        case .lan:
            useLAN = true
        case .cloud:
            useLAN = false
        case .auto:
            useLAN = probeOk == true
        }
        let next = useLAN ? resolvedLanIntent : cloudIntent
        let changed = next != intentServerURL
        intentServerURL = next
        intentClient.lastServerURL = next
        brainEnvironment.routing = routing
        brainEnvironment.lanProbeOk = probeOk
        brainEnvironment.lanProbeDetail = probeDetail
        brainEnvironment.mode = useLAN ? .lan : .cloud
        brainEnvironment.activeIntentURL = next

        DiscoveryDebugLog.shared.log(
            "resolveBrainEndpoint → mode=\(useLAN ? "lan" : "cloud") url=\(next) changed=\(changed) probeOk=\(String(describing: probeOk)) detail=\(probeDetail)",
            category: "connect"
        )

        if reregister, changed, !coldBootstrapRunning {
            await ensureRegistered(serverURL: next, force: true)
        }
    }

    private func startPathMonitor() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.applyPath(path)
            }
        }
        pathMonitor.start(queue: pathQueue)
    }

    private func applyPath(_ path: NWPath) {
        let kind: BrainPathKind
        if path.status != .satisfied {
            kind = .none
        } else if path.usesInterfaceType(.wifi) {
            kind = .wifi
        } else if path.usesInterfaceType(.wiredEthernet) {
            kind = .wired
        } else if path.usesInterfaceType(.cellular) {
            kind = .cellular
        } else {
            kind = .unknown
        }
        let looks = kind.looksOnHomeLAN
        let pathChanged = kind != brainEnvironment.pathKind
        brainEnvironment.pathKind = kind
        brainEnvironment.looksOnHomeLAN = looks
        if pathChanged {
            DiscoveryDebugLog.shared.log("network path → \(kind) looksOnHomeLAN=\(looks)", category: "connect")
            if coldBootstrapRunning {
                pendingPathResolve = true
            } else {
                Task { await resolveBrainEndpoint(reregister: true) }
            }
        }
    }

    /// If the fixed cadence already elapsed while suspended, fire once and reschedule from now.
    private func catchUpHeartbeatIfOverdue() async {
        let interval = Self.heartbeatIntervalSeconds
        let now = Date()
        let overdue: Bool
        if let next = nextHeartbeatAt {
            overdue = next <= now
        } else if let last = lastHeartbeatAt {
            overdue = now.timeIntervalSince(last) >= interval
        } else {
            overdue = true
        }
        guard overdue else { return }
        nextHeartbeatAt = now.addingTimeInterval(interval)
        // Restart so a stale sleep from before suspend cannot also fire.
        restartHeartbeatLoop()
        enqueueBrainHeartbeat(mode: .lan)
        enqueueBrainHeartbeat(mode: .cloud)
    }

    /// Pull latest logistics (step_log / action timings) before showing progress UI.
    func refreshTurnProgress(turnId: UUID, serverURL: String? = nil) async {
        let url = (serverURL ?? intentServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let idx = turns.firstIndex(where: { $0.id == turnId }) else { return }
        let intentId = turns[idx].intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ChatTurn.isBrainIntentId(intentId), !url.isEmpty else { return }

        if let snap = await intentClient.fetchIntentDetail(intentId: intentId, intentURL: url) {
            applyHydratedSnapshot(snap, to: idx)
            return
        }
        if let cached = IntentDetailCache.snapshot(for: intentId) {
            applyHydratedSnapshot(cached, to: idx)
            return
        }
        if JourneyLocalCache.load(intentId) != nil {
            turns[idx].journey = JourneyLocalCache.enrich(turns[idx].journey)
        }
    }

    func isDevBugBusy(turnId: UUID) -> Bool {
        devBugBusyTurnIds.contains(turnId)
    }

    func isDevBugSubmitted(intentId: String) -> Bool {
        DebugReportStore.isSubmitted(intentId: intentId)
    }

    func devBugError(for turnId: UUID) -> String? {
        devBugErrors[turnId]
    }

    func submitUserFeedback(
        turnId: UUID,
        problemType: UserFeedbackProblemType,
        detail: String = "",
        attachments: [PendingFeedbackAttachment] = [],
        completion: @escaping (Bool, String) -> Void
    ) {
        guard let turn = turns.first(where: { $0.id == turnId }) else {
            completion(false, "找不到对话")
            return
        }
        let intentId = turn.intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ChatTurn.isBrainIntentId(intentId) else {
            completion(false, "invalid intent_id")
            return
        }
        guard !isDevBugBusy(turnId: turnId), !isDevBugSubmitted(intentId: intentId) else {
            completion(false, "已提交过反馈")
            return
        }

        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            completion(false, "participant_id is required")
            return
        }

        devBugBusyTurnIds.insert(turnId)
        devBugErrors.removeValue(forKey: turnId)

        let snapshot = DebugClientSnapshot.build(
            env: brainEnvironment,
            intentServerURL: intentServerURL,
            lanHeartbeat: lanHeartbeat,
            cloudHeartbeat: cloudHeartbeat,
            clientHint: clientHint,
            journey: turn.journey,
            intentId: intentId
        )

        let trimmedDetail = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        let userSummary: String
        if problemType == .other {
            userSummary = trimmedDetail
        } else {
            userSummary = problemType.label
        }

        Task {
            var uploadedAttachments: [FeedbackAttachment] = []
            if !attachments.isEmpty {
                for (index, pending) in attachments.enumerated() {
                    do {
                        let uploaded = try await FeedbackAttachmentUpload.upload(
                            pending,
                            intentURL: intentServerURL,
                            intentId: intentId
                        )
                        uploadedAttachments.append(uploaded)
                    } catch {
                        devBugBusyTurnIds.remove(turnId)
                        let err = "附件 \(index + 1) 上传失败：\(error.localizedDescription)"
                        devBugErrors[turnId] = err
                        completion(false, err)
                        return
                    }
                }
            }

            let result = await intentClient.submitDebugReport(
                intentId: intentId,
                participantId: pid,
                intentURL: intentServerURL,
                clientSnapshot: snapshot,
                userSummary: userSummary,
                problemType: problemType.rawValue,
                attachments: uploadedAttachments
            )
            devBugBusyTurnIds.remove(turnId)
            if result.ok {
                DebugReportStore.markSubmitted(intentId: intentId)
                devBugErrors.removeValue(forKey: turnId)
                completion(true, result.message)
            } else {
                let err = result.error.isEmpty ? "提交失败" : result.error
                devBugErrors[turnId] = err
                completion(false, err)
            }
        }
    }

    func reportBug(turnId: UUID) {
        guard let turn = turns.first(where: { $0.id == turnId }) else { return }
        let intentId = turn.intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ChatTurn.isBrainIntentId(intentId) else { return }
        guard !isDevBugBusy(turnId: turnId), !isDevBugSubmitted(intentId: intentId) else { return }

        devBugBusyTurnIds.insert(turnId)
        devBugErrors.removeValue(forKey: turnId)

        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        let snapshot = DebugClientSnapshot.build(
            env: brainEnvironment,
            intentServerURL: intentServerURL,
            lanHeartbeat: lanHeartbeat,
            cloudHeartbeat: cloudHeartbeat,
            clientHint: clientHint,
            journey: turn.journey,
            intentId: intentId
        )

        Task {
            let result = await intentClient.submitDebugReport(
                intentId: intentId,
                participantId: pid,
                intentURL: intentServerURL,
                clientSnapshot: snapshot
            )
            devBugBusyTurnIds.remove(turnId)
            if result.ok {
                DebugReportStore.markSubmitted(intentId: intentId)
                devBugErrors.removeValue(forKey: turnId)
            } else {
                devBugErrors[turnId] = result.error.isEmpty ? "提交失败" : result.error
            }
        }
    }

    private func applyHydratedSnapshot(_ snapshot: IntentJobSnapshot, to idx: Int) {
        guard turns.indices.contains(idx) else { return }
        let hydrated = ChatTurn.fromHistory(snapshot)
        if !hydrated.userText.isEmpty {
            turns[idx].userText = hydrated.userText
        }
        if let at = snapshot.createdAt {
            turns[idx].createdAt = at
        }
        turns[idx].source = hydrated.source
        turns[idx].journey = JourneyLocalCache.enrich(hydrated.journey)
        turns[idx].assistantText = hydrated.assistantText
        turns[idx].awaitingTerminal = hydrated.awaitingTerminal
        JourneyLocalCache.save(turns[idx].journey)
        persistTurns()
        if hydrated.awaitingTerminal, !intentJourney.isPolling(snapshot.jobId) {
            resumePollingIfNeeded(serverURL: intentServerURL)
        }
    }

    /// Fixed-cadence loop: next fire is always `now + interval` after the previous
    /// *scheduled* tick. HTTP runs on independent LAN / Cloud queues and is not awaited.
    private func startHeartbeatLoopIfNeeded() {
        guard heartbeatLoop == nil else { return }
        let interval = Self.heartbeatIntervalSeconds
        if nextHeartbeatAt == nil {
            nextHeartbeatAt = Date().addingTimeInterval(interval)
        }
        heartbeatLoop = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let target = self.nextHeartbeatAt ?? Date().addingTimeInterval(interval)
                let delay = max(0, target.timeIntervalSinceNow)
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                guard !Task.isCancelled else { return }
                // Advance schedule before any HTTP so the countdown never sits at 0.
                self.nextHeartbeatAt = Date().addingTimeInterval(interval)
                self.enqueueBrainHeartbeat(mode: .lan)
                self.enqueueBrainHeartbeat(mode: .cloud)
            }
        }
    }

    private func restartHeartbeatLoop() {
        heartbeatLoop?.cancel()
        heartbeatLoop = nil
        startHeartbeatLoopIfNeeded()
    }

    /// P0 dual-Brain: classify an intent URL as LAN or Cloud for per-Brain status.
    private func brainMode(for url: String) -> BrainEndpoint.Mode {
        let lan = BrainEndpoint.intentURL(from: lanConnectBase())
        let cloud = BrainEndpoint.intentURL(from: cloudBrainURL)
        if url == cloud { return .cloud }
        return .lan
    }

    /// P0 dual-Brain: update the per-Brain heartbeat status (latest attempt +
    /// success + error). Called from both LAN and Cloud heartbeat paths.
    private func updateHeartbeatStatus(_ mode: BrainEndpoint.Mode, ok: Bool, at: Date, error: String) {
        var s = mode == .lan ? lanHeartbeat : cloudHeartbeat
        s.lastAttemptAt = at
        s.lastOk = ok
        s.lastError = ok ? "" : error
        if ok { s.lastSuccessAt = at }
        if mode == .lan { lanHeartbeat = s } else { cloudHeartbeat = s }
    }

    /// P0 dual-Brain: mark a Brain slot as registered (after a successful register).
    private func markRegistered(_ mode: BrainEndpoint.Mode, at: Date) {
        var s = mode == .lan ? lanHeartbeat : cloudHeartbeat
        s.registered = true
        s.registeredAt = at
        if mode == .lan { lanHeartbeat = s } else { cloudHeartbeat = s }
    }

    private func setHeartbeatPhase(_ mode: BrainEndpoint.Mode, _ phase: HeartbeatPhase) {
        if mode == .lan {
            lanHeartbeat.phase = phase
        } else {
            cloudHeartbeat.phase = phase
        }
        heartbeatBusy = lanHeartbeat.phase.isActive || cloudHeartbeat.phase.isActive
    }

    private func secondaryMode(for primaryURL: String) -> BrainEndpoint.Mode {
        brainMode(for: primaryURL) == .lan ? .cloud : .lan
    }

    private func intentURL(for mode: BrainEndpoint.Mode) -> String {
        mode == .lan
            ? BrainEndpoint.intentURL(from: lanConnectBase())
            : BrainEndpoint.intentURL(from: cloudBrainURL)
    }

    /// Independent per-Brain serial queue. A tick while in-flight coalesces to one follow-up.
    private func enqueueBrainHeartbeat(mode: BrainEndpoint.Mode) {
        switch mode {
        case .lan:
            if lanBeatInFlight {
                lanBeatPending = true
                return
            }
            lanBeatInFlight = true
        case .cloud:
            if cloudBeatInFlight {
                cloudBeatPending = true
                return
            }
            cloudBeatInFlight = true
        }
        Task { @MainActor [weak self] in
            await self?.runQueuedHeartbeat(mode: mode)
        }
    }

    private func runQueuedHeartbeat(mode: BrainEndpoint.Mode) async {
        defer {
            switch mode {
            case .lan:
                lanBeatInFlight = false
                if lanBeatPending {
                    lanBeatPending = false
                    enqueueBrainHeartbeat(mode: .lan)
                }
            case .cloud:
                cloudBeatInFlight = false
                if cloudBeatPending {
                    cloudBeatPending = false
                    enqueueBrainHeartbeat(mode: .cloud)
                }
            }
        }
        _ = await beatOneBrain(serverURL: intentURL(for: mode), mode: mode)
    }

    /// Beat one Brain only (3s × 3 attempts). Does not wait for the other Brain.
    @discardableResult
    func heartbeatNow(serverURL: String) async -> Bool {
        let mode = brainMode(for: serverURL)
        if beatInFlight(mode) {
            while beatInFlight(mode) {
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
            return (mode == .lan ? lanHeartbeat : cloudHeartbeat).lastOk
        }
        markBeatInFlight(mode, true)
        defer {
            markBeatInFlight(mode, false)
            drainPending(mode)
        }
        return await beatOneBrain(serverURL: serverURL, mode: mode)
    }

    private func beatInFlight(_ mode: BrainEndpoint.Mode) -> Bool {
        mode == .lan ? lanBeatInFlight : cloudBeatInFlight
    }

    private func markBeatInFlight(_ mode: BrainEndpoint.Mode, _ value: Bool) {
        if mode == .lan { lanBeatInFlight = value } else { cloudBeatInFlight = value }
    }

    private func drainPending(_ mode: BrainEndpoint.Mode) {
        switch mode {
        case .lan:
            if lanBeatPending {
                lanBeatPending = false
                enqueueBrainHeartbeat(mode: .lan)
            }
        case .cloud:
            if cloudBeatPending {
                cloudBeatPending = false
                enqueueBrainHeartbeat(mode: .cloud)
            }
        }
    }

    private func beatOneBrain(serverURL: String, mode: BrainEndpoint.Mode) async -> Bool {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let isPrimary = trimmed == intentServerURL
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            let err = "participant_id 为空，无法心跳"
            if isPrimary {
                applyHeartbeatResult(ok: false, at: Date(), error: err)
            }
            updateHeartbeatStatus(mode, ok: false, at: Date(), error: err)
            setHeartbeatPhase(mode, .idle)
            return false
        }
        setHeartbeatPhase(mode, .sending)
        let prepared = await intentClient.prepareHeartbeatBody(participantId: pid)
        guard let body = prepared.data else {
            let detail = prepared.error ?? "心跳 JSON 无法序列化"
            if isPrimary {
                applyHeartbeatResult(ok: false, at: Date(), error: detail)
            }
            updateHeartbeatStatus(mode, ok: false, at: Date(), error: detail)
            setHeartbeatPhase(mode, .idle)
            return false
        }

        var lastError = ""
        for attempt in 1 ... Self.heartbeatMaxAttempts {
            if attempt > 1 {
                setHeartbeatPhase(mode, .retrying(attempt: attempt))
                try? await Task.sleep(nanoseconds: UInt64(Self.heartbeatRetryGapSeconds * 1_000_000_000))
            } else {
                setHeartbeatPhase(mode, .sending)
            }
            let send = await intentClient.sendHeartbeat(
                serverURL: trimmed,
                participantId: pid,
                body: body,
                hardTimeout: Self.heartbeatAttemptTimeout
            )
            switch send {
            case let .ok(at, roles):
                if mode == .lan {
                    persistPingVerifiedLanBase(BrainEndpoint.displayBase(from: trimmed))
                }
                finishHeartbeatSuccess(mode: mode, isPrimary: isPrimary, at: at, roles: roles)
                return true
            case let .failed(detail):
                lastError = detail
                let needsRegister = detail.contains("register first") || detail.contains("401")
                guard needsRegister else { continue }
                if let reg = await intentClient.registerParticipant(
                    serverURL: trimmed,
                    timeout: Self.heartbeatAttemptTimeout
                ) {
                    markRegistered(mode, at: reg.ts ?? Date())
                    let retry = await intentClient.sendHeartbeat(
                        serverURL: trimmed,
                        participantId: pid,
                        body: body,
                        hardTimeout: Self.heartbeatAttemptTimeout
                    )
                    switch retry {
                    case let .ok(at, roles):
                        finishHeartbeatSuccess(mode: mode, isPrimary: isPrimary, at: at, roles: roles)
                        return true
                    case let .failed(detail2):
                        lastError = detail2
                    }
                } else {
                    lastError = "注册失败"
                }
            }
        }
        if isPrimary {
            applyHeartbeatResult(ok: false, at: Date(), error: lastError)
        }
        updateHeartbeatStatus(mode, ok: false, at: Date(), error: lastError)
        setHeartbeatPhase(mode, .idle)
        return false
    }

    private func finishHeartbeatSuccess(
        mode: BrainEndpoint.Mode,
        isPrimary: Bool,
        at: Date,
        roles: [String]
    ) {
        if mode == .lan {
            persistPingVerifiedLanBase(lanConnectBase())
        }
        if isPrimary {
            applyHeartbeatResult(ok: true, at: at, error: "")
        }
        updateHeartbeatStatus(mode, ok: true, at: at, error: "")
        applyReportedRoles(roles, for: mode, isPrimary: isPrimary)
        setHeartbeatPhase(mode, .idle)
        if isPrimary {
            Task { @MainActor [weak self] in
                await self?.syncRuntimeLoop()
            }
        }
    }

    /// Latest attempt updates `lastHeartbeatAt`; success also advances `lastHeartbeatSuccessAt`.
    private func applyHeartbeatResult(
        ok: Bool,
        at: Date,
        error: String
    ) {
        lastHeartbeatOk = ok
        lastHeartbeatAt = at
        lastHeartbeatError = ok ? "" : error
        if ok {
            lastHeartbeatSuccessAt = at
            ParticipantStore.lastHeartbeatAt = at
        }
        if !ok {
            NSLog("[heartbeat] %@", error)
        }
    }

    /// Record roles from a heartbeat that this Brain actually accepted.
    /// Failed heartbeats keep the previous list (UI shows — until the first success).
    private func applyReportedRoles(_ roles: [String], for mode: BrainEndpoint.Mode, isPrimary: Bool) {
        ParticipantStore.setLastReportedRoles(roles, for: mode)
        if mode == .lan {
            lanLastReportedRoles = roles
        } else {
            cloudLastReportedRoles = roles
        }
        if isPrimary {
            ParticipantStore.lastReportedRoles = roles
            lastReportedRoles = roles
        }
    }

    /// Click「对时」: show local time immediately, then ping LAN and Cloud in parallel.
    /// Snapshot is static for that click; unrelated to heartbeat / other UI.
    func syncClock() async {
        guard !clockSyncBusy else { return }
        clockSyncBusy = true
        defer { clockSyncBusy = false }
        let local = Date()
        clockSync = ClockSyncSample(localAt: local)
        clockSyncError = ""
        // Let SwiftUI paint 【本地时间】 before the network await.
        await Task.yield()
        let lanURL = BrainEndpoint.intentURL(from: lanConnectBase())
        let cloudURL = BrainEndpoint.intentURL(from: cloudBrainURL)
        async let lanPing = intentClient.ping(serverURL: lanURL, clientSentAt: local)
        async let cloudPing = intentClient.ping(serverURL: cloudURL, clientSentAt: local)
        let (lan, cloud) = await (lanPing, cloudPing)
        var sample = ClockSyncSample(localAt: local)
        switch lan {
        case let .ok(serverAt, skewMs):
            sample.lanServerAt = serverAt
            sample.lanSkewMs = skewMs
            await adoptLanFromSuccessfulPing()
        case let .failed(detail):
            sample.lanError = detail
        }
        switch cloud {
        case let .ok(serverAt, skewMs):
            sample.cloudServerAt = serverAt
            sample.cloudSkewMs = skewMs
        case let .failed(detail):
            sample.cloudError = detail
        }
        clockSync = sample
        clockSyncError = ""
    }

    func clearSession() {
        intentJourney.clear()
        turns = []
        lastResponse = ""
        historyNotice = ""
        historyNextBeforeId = nil
        historyExhausted = false
        skipScrollToLatest = false
        ChatPersistence.clear()
    }

    func setRole(_ role: String, enabled: Bool) {
        ParticipantStore.setRole(role, enabled: enabled)
        enabledRoles = ParticipantStore.reportedRoles
    }

    private func syncRuntimeLoop() async {
        if lastReportedRoles.contains("runtime") {
            await RuntimeLoop.shared.start()
        } else {
            await RuntimeLoop.shared.stop()
        }
    }

    func sendIntent(text: String, source: String, serverURL: String) async {
        await sendIntent(text: text, source: source, serverURL: serverURL, assetRef: nil, previewAssetId: nil)
    }

    /// One-tap Visual Input: Image Asset already created → submit to Agent Session.
    func sendVisualInput(
        assetRef: [String: Any],
        previewAssetId: String,
        serverURL: String,
        prompt: String = "（视觉输入）请看这张图"
    ) async {
        await sendIntent(
            text: prompt,
            source: "visual",
            serverURL: serverURL,
            assetRef: assetRef,
            previewAssetId: previewAssetId
        )
    }

    /// Pronunciation assessment entry: both audio Assets already uploaded (their
    /// asset_refs in hand) → submit an intent whose context carries the two named
    /// audio refs so the Brain planner can wire $reference_audio / $student_audio
    /// into the pronunciation.assess step. The actual recording/upload UI is owned
    /// by the audio workspace; this just dispatches the assembled refs.
    func sendPronunciationAssessment(
        referenceAssetRef: [String: Any],
        studentAssetRef: [String: Any],
        serverURL: String,
        prompt: String = "评测这段跟读"
    ) async {
        await sendIntent(
            text: prompt,
            source: "text",
            serverURL: serverURL,
            assetRef: nil,
            previewAssetId: nil,
            context: [
                "reference_audio": referenceAssetRef,
                "student_audio": studentAssetRef,
            ]
        )
    }

    private func sendIntent(
        text: String,
        source: String,
        serverURL _: String,
        assetRef: [String: Any]?,
        previewAssetId: String?,
        context: [String: Any]? = nil
    ) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        await resolveBrainEndpoint(reregister: true)
        let serverURL = intentServerURL
        intentClient.lastServerURL = serverURL
        await ensureRegistered(serverURL: serverURL)
        let beatOk = await heartbeatNow(serverURL: serverURL)
        guard beatOk else {
            let turnId = UUID()
            turns.append(
                ChatTurn(
                    id: turnId,
                    intentId: "",
                    createdAt: Date(),
                    userText: trimmed,
                    source: source,
                    journey: IntentJourneyStore.dispatchFailed(
                        text: trimmed,
                        detail: "心跳失败，未发出。请确认 Brain 可达后重试。"
                    ),
                    assistantText: "心跳失败，未发出。请确认 Brain 可达后重试。",
                    awaitingTerminal: false,
                    inputAssetId: previewAssetId
                )
            )
            persistTurns()
            return
        }

        let turnId = UUID()
        let t0 = Date()
        var pendingJourney = IntentJourney.make(jobId: "pending…", text: trimmed, status: .uploaded)
        pendingJourney.clientStartedAt = t0
        let turn = ChatTurn(
            id: turnId,
            intentId: "",
            createdAt: t0,
            userText: trimmed,
            source: source,
            journey: pendingJourney,
            assistantText: nil,
            awaitingTerminal: true,
            inputAssetId: previewAssetId
        )
        turns.append(turn)
        sending = true
        defer { sending = false }

        let result = await intentClient.dispatch(
            text: trimmed,
            source: source,
            serverURL: serverURL,
            assetRef: assetRef,
            context: context
        )
        lastResponse = result.message

        guard result.ok, let snapshot = result.snapshot else {
            let detail = result.message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "发出失败"
                : String(result.message.prefix(200))
            applyJourney(
                IntentJourneyStore.dispatchFailed(text: trimmed, detail: detail),
                to: turnId,
                finished: true
            )
            return
        }

        let prior = turns.first(where: { $0.id == turnId })?.journey
        var seeded = IntentJourneyStore.journeyFromPost(snapshot, preservingClientFrom: prior)
        seeded.clientStartedAt = prior?.clientStartedAt ?? t0
        if let idx = turns.firstIndex(where: { $0.id == turnId }) {
            turns[idx].intentId = snapshot.jobId
            turns[idx].journey = seeded
        }
        startPolling(turnId: turnId, jobId: snapshot.jobId, seed: seeded, serverURL: serverURL)
        if lastReportedRoles.contains("runtime") {
            await RuntimeLoop.shared.pullNow()
        }
        persistTurns()
    }

    /// 扫描页入口：立刻打开系统扫描仪，上传到 POST /api/v1/assets/upload；不经 Planner。
    func runLocalDocumentScan(serverURL: String) async {
        let url = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        scanBusy = true
        scanHint = ""
        defer { scanBusy = false }
        do {
            let asset = try await VisualInput.captureAndCreateAsset(
                intentURL: url,
                intentId: nil,
                uploadIntent: VisualInput.uploadIntentDocumentScan
            )
            let aid = asset.assetId
            ScanPreviewStore.save(assetId: aid, image: asset.localImage)
            turns.append(
                ChatTurn(
                    id: UUID(),
                    intentId: "scan-\(aid)",
                    createdAt: Date(),
                    userText: "扫描",
                    source: "document.scan",
                    journey: IntentJourney.make(
                        jobId: "scan-\(aid)",
                        text: "扫描",
                        status: .succeeded
                    ),
                    assistantText: "已上传扫描图 asset_id=\(aid)",
                    awaitingTerminal: false,
                    inputAssetId: aid,
                    uploadStatus: .uploaded
                )
            )
            persistTurns()
        } catch let e as VisualInput.InputError where e.isCancelled {
            return
        } catch {
            scanHint = error.localizedDescription
        }
    }

    /// 拍照页快门：拍摄已成功（UIImage 在手）→ 立刻落本机存储并写入本地列表，
    /// UI 立即可见、可马上拍下一张；上传由后台自动进行，不经 Planner。
    /// 拍摄侧失败（无法留存本机）才报「拍照失败」；上传失败只标记该照片的上传状态。
    func registerLocalIPhonePhoto(image: UIImage) {
        photoHint = ""
        let localId = LocalPhotoStore.makeId()
        do {
            try LocalPhotoStore.save(image: image, localId: localId)
        } catch {
            photoHint = "拍照失败：照片没能写入本机存储。（\(error.localizedDescription)）"
            return
        }
        ScanPreviewStore.save(assetId: localId, image: image)
        let turnId = UUID()
        let jobId = "photo-\(localId)"
        turns.append(
            ChatTurn(
                id: turnId,
                intentId: jobId,
                createdAt: Date(),
                userText: "拍照",
                source: "iphone.photo",
                journey: IntentJourney.make(
                    jobId: jobId,
                    text: "拍照",
                    status: .succeeded
                ),
                assistantText: "已拍照 · 等待上传",
                awaitingTerminal: false,
                inputAssetId: localId,
                uploadStatus: .pending
            )
        )
        persistTurns()
        Task { await self.uploadLocalPhoto(turnId: turnId) }
    }

    /// Background upload of one locally held photo. Never blocks capture; the
    /// outcome only updates that photo's own upload status.
    func uploadLocalPhoto(turnId: UUID) async {
        guard let idx = turns.firstIndex(where: { $0.id == turnId }),
              turns[idx].isIPhonePhoto
        else { return }
        let localId = (turns[idx].inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard LocalPhotoStore.isLocalId(localId) else { return }
        guard turns[idx].uploadStatus != .uploading else { return }
        turns[idx].uploadStatus = .uploading
        turns[idx].assistantText = "已拍照 · 上传中…"
        do {
            let data = try LocalPhotoStore.read(localId: localId)
            let url = intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !url.isEmpty else {
                throw VisualInput.InputError.message("上传失败：请先在设置里填写 Brain URL。")
            }
            let created = turns[idx].createdAt
            let asset = try await VisualInput.uploadFile(
                data: data,
                filename: "photo_\(Int(created.timeIntervalSince1970)).jpg",
                mimeType: "image/jpeg",
                type: "image",
                intentURL: url,
                uploadIntent: VisualInput.uploadIntentIPhonePhoto
            )
            guard let done = turns.firstIndex(where: { $0.id == turnId }) else { return }
            let aid = asset.assetId
            if let image = UIImage(data: data) {
                ScanPreviewStore.save(assetId: aid, image: image)
            }
            ScanPreviewStore.remove(assetId: localId)
            LocalPhotoStore.remove(localId: localId)
            turns[done].inputAssetId = aid
            turns[done].intentId = "photo-\(aid)"
            turns[done].journey = IntentJourney.make(jobId: "photo-\(aid)", text: "拍照", status: .succeeded)
            turns[done].assistantText = "已上传照片 asset_id=\(aid)"
            turns[done].uploadStatus = .uploaded
            persistTurns()
        } catch {
            guard let failed = turns.firstIndex(where: { $0.id == turnId }) else { return }
            turns[failed].uploadStatus = .failed
            if case LocalPhotoStore.StoreError.missing = error {
                turns[failed].assistantText = "上传失败：本机照片文件已丢失，无法重试。"
            } else {
                let reason = error.localizedDescription
                let detail = reason.hasPrefix("上传失败") ? reason : "上传失败：\(reason)"
                turns[failed].assistantText = "\(detail)（照片已存本机，可点重试）"
            }
            persistTurns()
        }
    }

    /// Manual retry from the photo row after an upload failure.
    func retryPhotoUpload(turnId: UUID) {
        Task { await uploadLocalPhoto(turnId: turnId) }
    }

    /// Re-queue every locally held photo whose upload never finished. Runs after
    /// cold bootstrap and on foreground, so a photo taken while Brain was
    /// unreachable still uploads itself later without blocking new captures.
    func resumePendingPhotoUploads() {
        for turn in turns where turn.isIPhonePhoto {
            let aid = (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard LocalPhotoStore.isLocalId(aid) else { continue }
            guard turn.uploadStatus == .pending || turn.uploadStatus == .failed else { continue }
            Task { await uploadLocalPhoto(turnId: turn.id) }
        }
    }

    /// 文件页：从 Files / iCloud / 本机选文件 → POST /api/v1/assets/upload；不经 Planner。
    func runLocalFileUpload(url: URL, serverURL: String) async {
        let scoped = url.startAccessingSecurityScopedResource()
        defer {
            if scoped { url.stopAccessingSecurityScopedResource() }
        }
        do {
            let data = try Data(contentsOf: url)
            let filename = VisualInput.sanitizedFilename(url.lastPathComponent)
            let ext = (filename as NSString).pathExtension
            let values = try? url.resourceValues(forKeys: [.contentTypeKey])
            let mime = values?.contentType?.preferredMIMEType
                ?? UTType(filenameExtension: ext)?.preferredMIMEType
                ?? "application/octet-stream"
            await runLocalFileUpload(
                data: data,
                filename: filename,
                mimeType: mime,
                serverURL: serverURL
            )
        } catch {
            fileHint = error.localizedDescription
        }
    }

    /// 文件页：相册选图或其它已读入内存的字节 → 同上上传路径。
    func runLocalFileUpload(
        data: Data,
        filename: String,
        mimeType: String,
        serverURL: String
    ) async {
        let server = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else { return }
        guard !data.isEmpty else {
            fileHint = "选中的内容为空，请重试。"
            return
        }
        fileBusy = true
        fileHint = ""
        let safeName = VisualInput.sanitizedFilename(filename)
        fileUploadingName = safeName
        defer {
            fileBusy = false
            fileUploadingName = ""
        }
        do {
            let mime = mimeType.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "application/octet-stream"
                : mimeType
            let type = VisualInput.inferAssetType(mimeType: mime, filename: safeName)
            let asset = try await VisualInput.uploadFile(
                data: data,
                filename: safeName,
                mimeType: mime,
                type: type,
                intentURL: server
            )
            let aid = asset.assetId
            if let image = asset.localImage {
                ScanPreviewStore.save(assetId: aid, image: image)
            }
            turns.append(
                ChatTurn(
                    id: UUID(),
                    intentId: "file-\(aid)",
                    createdAt: Date(),
                    userText: asset.filename,
                    source: "iphone.file",
                    journey: IntentJourney.make(
                        jobId: "file-\(aid)",
                        text: asset.filename,
                        status: .succeeded
                    ),
                    assistantText: "已上传文件 asset_id=\(aid) · \(asset.type)",
                    awaitingTerminal: false,
                    inputAssetId: aid
                )
            )
            persistTurns()
        } catch let e as VisualInput.InputError where e.isCancelled {
            return
        } catch {
            fileHint = error.localizedDescription
        }
    }

    func startLocalAudio() async {
        audioHint = ""
        if audioRecorder.isActive { return }
        audioPlayer.stop(deactivate: true)
        audioTitle = AudioRecorder.defaultTitle()
        let started = await audioRecorder.start { [weak self] in
            guard let self else { return }
            Task { await self.stopAndUploadLocalAudio(serverURL: self.intentServerURL) }
        }
        if !started {
            audioHint = audioRecorder.lastError
        }
    }

    func pauseLocalAudio() {
        audioRecorder.pause()
        audioHint = audioRecorder.lastError
    }

    func resumeLocalAudio() {
        audioRecorder.resume()
        audioHint = audioRecorder.lastError
    }

    /// Recording (not paused) leaving the pane: stop and upload. Paused stays paused.
    func handleAudioPaneDisappear() {
        guard audioRecorder.isRecording else { return }
        Task { await stopAndUploadLocalAudio(serverURL: intentServerURL) }
    }

    func playLocalAudio(assetId: String) {
        audioHint = ""
        guard !audioRecorder.isRecording else { return }
        if !audioPlayer.play(assetId: assetId) {
            audioHint = audioPlayer.lastError
        }
    }

    func pauseLocalAudioPlayback() {
        audioPlayer.pause()
    }

    func seekLocalAudioPlayback(_ seconds: TimeInterval) {
        audioPlayer.seek(seconds)
    }

    func renameLocalAudio(turnId: UUID, name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard let idx = turns.firstIndex(where: { $0.id == turnId }), turns[idx].isIPhoneAudio else { return }
        turns[idx].userText = trimmed
        persistTurns()
    }

    /// 录音页停止：封盘后 POST /api/v1/assets/upload；不经 Planner。暂停不得调用本方法。
    func stopAndUploadLocalAudio(serverURL: String) async {
        guard audioRecorder.isActive, !audioBusy else { return }
        audioBusy = true
        audioHint = ""
        let keepSession = audioPlayer.isActive
        let fileURL = audioRecorder.stop(deactivateSession: !keepSession)
        defer { audioBusy = false }
        guard let fileURL else {
            audioHint = audioRecorder.lastError.isEmpty ? "录音失败：没有文件。" : audioRecorder.lastError
            return
        }
        let server = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if server.isEmpty {
            audioHint = "请先在设置里填写 Brain URL"
            try? FileManager.default.removeItem(at: fileURL)
            return
        }
        let rawName = audioTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let base = rawName.isEmpty ? AudioRecorder.defaultTitle() : rawName
        let filename = VisualInput.sanitizedFilename(base.hasSuffix(".m4a") ? base : "\(base).m4a")
        do {
            let data = try Data(contentsOf: fileURL)
            let asset = try await VisualInput.uploadFile(
                data: data,
                filename: filename,
                mimeType: "audio/mp4",
                type: "audio",
                intentURL: server,
                uploadIntent: VisualInput.uploadIntentIPhoneAudio
            )
            let aid = asset.assetId
            AudioPreviewStore.save(assetId: aid, data: data)
            try? FileManager.default.removeItem(at: fileURL)
            let display = (asset.filename as NSString).deletingPathExtension
            let title = display.isEmpty ? base : display
            turns.append(
                ChatTurn(
                    id: UUID(),
                    intentId: "audio-\(aid)",
                    createdAt: Date(),
                    userText: title,
                    source: "iphone.audio",
                    journey: IntentJourney.make(
                        jobId: "audio-\(aid)",
                        text: title,
                        status: .succeeded
                    ),
                    assistantText: "已上传录音 asset_id=\(aid) · audio",
                    awaitingTerminal: false,
                    inputAssetId: aid
                )
            )
            persistTurns()
            audioTitle = ""
        } catch let e as VisualInput.InputError where e.isCancelled {
            return
        } catch {
            audioHint = error.localizedDescription
        }
    }

    func journey(for turnId: UUID) -> IntentJourney? {
        turns.first(where: { $0.id == turnId })?.journey
    }

    private func startPolling(
        turnId: UUID,
        jobId: String,
        seed: IntentJourney,
        serverURL: String
    ) {
        let url = serverURL
        intentJourney.startPolling(
            jobId: jobId,
            seed: seed,
            fetch: { [weak self] id in
                await self?.intentClient.fetchIntentDetail(intentId: id, intentURL: url)
            },
            onUpdate: { [weak self] journey in
                self?.applyJourney(journey, to: turnId, finished: journey.terminal || journey.timedOut)
            }
        )
    }

    private func applyJourney(_ journey: IntentJourney, to turnId: UUID, finished: Bool) {
        guard let idx = turns.firstIndex(where: { $0.id == turnId }) else { return }
        var next = journey
        if next.clientStartedAt == nil {
            next.clientStartedAt = turns[idx].journey.clientStartedAt ?? turns[idx].createdAt
        }
        if finished {
            next.stampClientFinishedIfNeeded()
        }
        turns[idx].journey = next
        if !next.jobId.isEmpty, next.jobId != "pending…" {
            turns[idx].intentId = next.jobId
            JourneyLocalCache.save(next)
        }
        if finished {
            turns[idx].assistantText = ChatTurn.assistantText(for: next)
            turns[idx].awaitingTerminal = false
            persistTurns()
        }
    }

    func loadOlderHistory(serverURL: String, silent: Bool = false) async {
        let url = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }

        await ensureRegistered(serverURL: url)
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            historyNotice = "尚未登记 participant，无法拉历史"
            return
        }

        if historyExhausted {
            historyNotice = "没有更早的本机历史"
            return
        }

        let oldestShown = turns.compactMap { Int($0.intentId) }.min()
        let before: Int?
        if let scanned = historyNextBeforeId {
            before = scanned
        } else if let oldestShown {
            before = oldestShown
        } else {
            before = nil
        }

        let wasEmpty = conversationTurns.isEmpty
        let page = await intentClient.fetchIssuerHistory(
            participantId: pid,
            beforeId: before,
            intentURL: url,
            limit: IntentClient.historyPageLimit
        )
        historyNextBeforeId = page.nextBeforeId
        if page.exhausted {
            historyExhausted = true
        }

        let existing = Set(turns.map(\.intentId).filter { !$0.isEmpty })
        let incoming = page.snapshots
            .filter { !existing.contains($0.jobId) }
            .map { ChatTurn.fromHistory($0) }

        if incoming.isEmpty {
            if silent {
                if turns.isEmpty {
                    historyNotice = ""
                }
            } else {
                historyNotice = historyExhausted ? "没有更早的本机历史" : "这一页没有本机记录，可再下拉"
            }
            return
        }

        historyNotice = ""
        skipScrollToLatest = !wasEmpty
        turns = Self.sortedTurns(incoming + turns)
        persistTurns()
        resumePollingIfNeeded(serverURL: url)
    }

    func consumeSkipScrollToLatest() -> Bool {
        let skip = skipScrollToLatest
        skipScrollToLatest = false
        return skip
    }

    private func persistTurns() {
        ChatPersistence.save(turns)
    }

    /// Refresh recent turns from Brain. Prefer open (awaiting) ones so startup
    /// does not serially GET every cached intent when the network is slow/down.
    private func refreshVisibleTurns(serverURL: String, onlyAwaiting: Bool = false) async {
        let candidates: [ChatTurn]
        if onlyAwaiting {
            candidates = turns.filter { $0.awaitingTerminal }
        } else {
            candidates = turns
        }
        let ids = candidates
            .suffix(Self.maxStartupDetailRefresh)
            .map(\.intentId)
            .filter { ChatTurn.isBrainIntentId($0) }
        guard !ids.isEmpty else {
            resumePollingIfNeeded(serverURL: serverURL)
            return
        }
        for intentId in ids {
            guard let idx = turns.firstIndex(where: { $0.intentId == intentId }) else { continue }
            if let snap = await intentClient.fetchIntentDetail(intentId: intentId, intentURL: serverURL) {
                applyHydratedSnapshot(snap, to: idx)
                continue
            }
            if let cached = IntentDetailCache.snapshot(for: intentId) {
                applyHydratedSnapshot(cached, to: idx)
                continue
            }
            if JourneyLocalCache.load(intentId) != nil {
                turns[idx].journey = JourneyLocalCache.enrich(turns[idx].journey)
            }
        }
        resumePollingIfNeeded(serverURL: serverURL)
    }

    private static func sortedTurns(_ items: [ChatTurn]) -> [ChatTurn] {
        items.sorted { a, b in
            if a.createdAt != b.createdAt { return a.createdAt < b.createdAt }
            let ai = Int(a.intentId) ?? Int.max
            let bi = Int(b.intentId) ?? Int.max
            return ai < bi
        }
    }

    private func resumePollingIfNeeded(serverURL: String) {
        for turn in turns where turn.awaitingTerminal && ChatTurn.isBrainIntentId(turn.intentId) {
            guard !intentJourney.isPolling(turn.intentId) else { continue }
            startPolling(
                turnId: turn.id,
                jobId: turn.intentId,
                seed: turn.journey,
                serverURL: serverURL
            )
        }
    }

    func ensureRegistered(serverURL: String, force: Bool = false) async {
        let url = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        let known = ParticipantStore.participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !force, !known.isEmpty, ParticipantStore.lastRegisteredBrainURL == url {
            participantId = known
            clientHint = ParticipantStore.clientHint
            registeredAt = ParticipantStore.registeredAt
            // P0 dual-Brain: keep the active Brain slot's registered flag in sync.
            markRegistered(brainMode(for: url), at: ParticipantStore.registeredAt ?? Date())
            return
        }
        guard let result = await intentClient.registerParticipant(serverURL: url) else {
            clientHint = ParticipantStore.clientHint
            return
        }
        let pid = result.id
        let prev = ParticipantStore.participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        ParticipantStore.participantId = pid
        if prev != pid || ParticipantStore.registeredAt == nil {
            ParticipantStore.registeredAt = result.ts ?? Date()
        }
        ParticipantStore.lastRegisteredBrainURL = url
        participantId = pid
        clientHint = ParticipantStore.clientHint
        registeredAt = ParticipantStore.registeredAt
        // P0 dual-Brain: mark the active Brain slot as registered.
        markRegistered(brainMode(for: url), at: ParticipantStore.registeredAt ?? Date())
    }
}
