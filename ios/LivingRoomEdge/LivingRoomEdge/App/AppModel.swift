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
    /// Per-photo background upload state (iphone.photo turns only).
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
                    uploadStatus: turn.uploadStatus == .uploading
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

    /// Only iphone.photo turns carry an upload state. `uploading` never survives a
    /// relaunch (no upload is in flight), so it comes back as `pending` and the
    /// bootstrap re-queues it. Records written before this field existed derive
    /// from the id shape: local `ph_…` id → still pending, real asset_id → uploaded.
    private static func restoredUploadStatus(source: String, raw: String?, assetId: String) -> LocalMediaUploadStatus? {
        guard source == "iphone.photo" else { return nil }
        if let raw, let value = LocalMediaUploadStatus(rawValue: raw) {
            return value == .uploading ? .pending : value
        }
        return LocalPhotoStore.isLocalId(assetId) ? .pending : .uploaded
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
    /// Wall time of the most recent heartbeat *attempt* (success or fail).
    @Published private(set) var lastHeartbeatAt = ParticipantStore.lastHeartbeatAt
    /// Wall time of the most recent *successful* heartbeat (persisted).
    @Published private(set) var lastHeartbeatSuccessAt = ParticipantStore.lastHeartbeatAt
    @Published private(set) var enabledRoles = ParticipantStore.reportedRoles
    @Published private(set) var lastReportedRoles = ParticipantStore.lastReportedRoles
    @Published private(set) var nextHeartbeatAt: Date?
    @Published private(set) var clockSync: ClockSyncSample?
    @Published private(set) var clockSyncBusy = false
    @Published private(set) var clockSyncError = ""
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
    private var heartbeatInFlight = false
    /// Suppress duplicate foreground work while cold-start bootstrap is still running.
    private var coldBootstrapRunning = true
    /// Keep ≤ Brain `ONLINE_TTL_SEC / 2` (TTL is 2× heartbeat).
    static let heartbeatIntervalSeconds: TimeInterval = 30
    /// Cap serial intent_detail refresh so a dead Brain cannot stall the UI for minutes.
    private static let maxStartupDetailRefresh = 8

    private var cancellables = Set<AnyCancellable>()
    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "livingroom.brain.path")

    private init() {
        ParticipantStore.applyGoProPreinstall()
        enabledRoles = ParticipantStore.reportedRoles
        turns = ChatPersistence.load()
        lanBrainURL = BrainEndpoint.lanBaseURL
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

        Task {
            // Let the first TabView frame paint before any network / @Published storm.
            await Task.yield()
            await resolveBrainEndpoint(reregister: false)
            let url = intentServerURL
            await ensureRegistered(serverURL: url, force: true)
            _ = await heartbeatNow(serverURL: url)
            startHeartbeatLoopIfNeeded()
            await loadOlderHistory(serverURL: url, silent: true)
            await refreshVisibleTurns(serverURL: url, onlyAwaiting: true)
            coldBootstrapRunning = false
            resumePendingPhotoUploads()
        }
    }

    func onForeground() {
        Task {
            // Cold-start Task already registers / heartbeats / refreshes.
            // scenePhase → .active often fires in the same window and must not double-run.
            guard !coldBootstrapRunning else { return }
            await resolveBrainEndpoint(reregister: true)
            // Brief Control Center flips: nextHeartbeatAt still in the future → no beat.
            // Long background suspend: cadence overdue → one catch-up beat, then resume 30s.
            await catchUpHeartbeatIfOverdue()
            await refreshVisibleTurns(serverURL: intentServerURL, onlyAwaiting: true)
            resumePendingPhotoUploads()
        }
    }

    func applyPinnedBrainURLs() async {
        BrainEndpoint.lanBaseURL = lanBrainURL
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
            ? BrainEndpoint.displayBase(from: lanBrainURL)
            : BrainEndpoint.displayBase(from: cloudBrainURL)
    }

    func applyBrainRouting(_ routing: BrainEndpoint.Routing) {
        brainRouting = routing
    }

    /// Auto: LAN when `/api/v1/ping` succeeds, else Cloud. Forced LAN / Cloud skip that choice.
    func resolveBrainEndpoint(reregister: Bool) async {
        while brainResolveBusy {
            try? await Task.sleep(nanoseconds: 80_000_000)
        }
        brainResolveBusy = true
        defer { brainResolveBusy = false }

        let routing = brainRouting
        let lanIntent = BrainEndpoint.intentURL(from: lanBrainURL)
        let cloudIntent = BrainEndpoint.intentURL(from: cloudBrainURL)
        let looksLAN = brainEnvironment.looksOnHomeLAN
        var probeOk: Bool?
        var probeDetail = ""

        let shouldProbeLAN = routing != .cloud && (looksLAN || routing == .lan)
        if shouldProbeLAN {
            switch await intentClient.ping(serverURL: lanIntent, clientSentAt: Date(), timeout: 2) {
            case .ok:
                probeOk = true
                probeDetail = ""
            case let .failed(detail):
                probeOk = false
                probeDetail = detail
            }
        } else if routing == .cloud {
            probeOk = nil
            probeDetail = "已强制走云 Brain，跳过 LAN 探测"
        } else {
            probeOk = false
            probeDetail = "当前不是家庭局域网，跳过 LAN 探测"
        }

        let useLAN: Bool
        switch routing {
        case .lan:
            useLAN = true
        case .cloud:
            useLAN = false
        case .auto:
            useLAN = probeOk == true
        }
        let next = useLAN ? lanIntent : cloudIntent
        let changed = next != intentServerURL
        intentServerURL = next
        intentClient.lastServerURL = next
        brainEnvironment.routing = routing
        brainEnvironment.lanProbeOk = probeOk
        brainEnvironment.lanProbeDetail = probeDetail
        brainEnvironment.mode = useLAN ? .lan : .cloud
        brainEnvironment.activeIntentURL = next

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
        if pathChanged, !coldBootstrapRunning {
            Task { await resolveBrainEndpoint(reregister: true) }
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
        _ = await heartbeatNow(serverURL: intentServerURL)
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
    /// *scheduled* tick, independent of success/fail and of ad-hoc heartbeats.
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
                // Advance schedule before awaiting HTTP so cadence does not drift
                // with RTT or success/fail.
                self.nextHeartbeatAt = Date().addingTimeInterval(interval)
                // Do not resolve/probe on this cadence: LAN ping on GoPro Wi‑Fi
                // can hang TCP connect far past the 30s slot and freeze the
                // countdown at 0. Routing / path changes resolve separately.
                await self.heartbeatNow(serverURL: self.intentServerURL)
            }
        }
    }

    private func restartHeartbeatLoop() {
        heartbeatLoop?.cancel()
        heartbeatLoop = nil
        startHeartbeatLoopIfNeeded()
    }

    @discardableResult
    func heartbeatNow(serverURL: String) async -> Bool {
        if heartbeatInFlight {
            return lastHeartbeatOk
        }
        heartbeatInFlight = true
        heartbeatBusy = true
        defer {
            heartbeatInFlight = false
            heartbeatBusy = false
        }
        await ensureRegistered(serverURL: serverURL)
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            applyHeartbeatResult(ok: false, at: Date(), error: "participant_id 为空，无法心跳", roles: nil)
            return false
        }
        switch await intentClient.sendHeartbeat(
            serverURL: serverURL,
            participantId: pid
        ) {
        case let .ok(at, roles):
            applyHeartbeatResult(ok: true, at: at, error: "", roles: roles)
            await syncRuntimeLoop()
            return true
        case let .failed(detail):
            applyHeartbeatResult(ok: false, at: Date(), error: detail, roles: nil)
            return false
        }
    }

    /// Latest attempt updates `lastHeartbeatAt`; success also advances `lastHeartbeatSuccessAt`.
    private func applyHeartbeatResult(
        ok: Bool,
        at: Date,
        error: String,
        roles: [String]?
    ) {
        lastHeartbeatOk = ok
        lastHeartbeatAt = at
        lastHeartbeatError = ok ? "" : error
        if ok {
            lastHeartbeatSuccessAt = at
            ParticipantStore.lastHeartbeatAt = at
            if let roles {
                ParticipantStore.lastReportedRoles = roles
                lastReportedRoles = roles
            }
        }
        if !ok {
            NSLog("[heartbeat] %@", error)
        }
    }

    /// Click「对时」: show local time immediately, then fill server time + skew from ping.
    /// Snapshot is static for that click; unrelated to heartbeat / other UI.
    func syncClock() async {
        guard !clockSyncBusy else { return }
        clockSyncBusy = true
        defer { clockSyncBusy = false }
        let local = Date()
        clockSync = ClockSyncSample(localAt: local, serverAt: nil, skewMs: nil)
        clockSyncError = ""
        // Let SwiftUI paint 【本地时间】 before the network await.
        await Task.yield()
        switch await intentClient.ping(serverURL: intentServerURL, clientSentAt: local) {
        case let .ok(serverAt, skewMs):
            clockSync = ClockSyncSample(localAt: local, serverAt: serverAt, skewMs: skewMs)
            clockSyncError = ""
        case let .failed(detail):
            clockSyncError = detail
        }
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

    private func sendIntent(
        text: String,
        source: String,
        serverURL _: String,
        assetRef: [String: Any]?,
        previewAssetId: String?
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
            assetRef: assetRef
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
                    inputAssetId: aid
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
        let server = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else { return }
        fileBusy = true
        fileHint = ""
        fileUploadingName = VisualInput.sanitizedFilename(url.lastPathComponent)
        defer {
            fileBusy = false
            fileUploadingName = ""
        }
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
            let type = VisualInput.inferAssetType(mimeType: mime, filename: filename)
            let asset = try await VisualInput.uploadFile(
                data: data,
                filename: filename,
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
    }
}
