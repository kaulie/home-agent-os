import Foundation
import Network

@MainActor
final class DevStore: ObservableObject {
    @Published var lanDraft: String = DevBrainEndpoint.lanBaseURL
    @Published var cloudDraft: String = DevBrainEndpoint.cloudBaseURL
    @Published var brainRouting: DevBrainEndpoint.Routing = DevBrainEndpoint.routing
    @Published private(set) var brainEnvironment = DevBrainEnvironment()
    @Published var brainResolveBusy = false

    @Published var tokenDraft: String = DevSettings.adminToken
    @Published var loadError: String?

    @Published var devTaskDraft = ""
    @Published var devTaskCategory = "tech_discuss"
    @Published var devTaskCategoryFilter = ""
    @Published private(set) var issues: [DebugIssue] = []
    @Published var issuesError: String?
    @Published var issuesExhausted = false
    @Published var isLoadingIssues = false

    @Published private(set) var devTasks: [DevTask] = []
    @Published var devTasksError: String?
    @Published var devTasksExhausted = false
    @Published var isLoadingDevTasks = false
    @Published var isSendingDevTask = false
    @Published var isCancellingDevTask = false

    @Published var statsPeriod = "week"
    @Published private(set) var statsUsage: DevTokenUsageStats?
    @Published var statsError: String?
    @Published var isLoadingStats = false

    @Published private(set) var fleetSnapshot: FleetSnapshot?
    @Published var fleetError: String?
    @Published var isLoadingFleet = false
    @Published var isWakingFleet = false

    @Published private(set) var deploySnapshot: DeploySnapshot?
    @Published var deployError: String?
    @Published var isLoadingDeploy = false
    @Published var isApprovingDeploy = false

    @Published private(set) var chatMessages: [AgentChatMessage] = []
    @Published var chatError: String?
    @Published var isLoadingChat = false
    @Published var isSendingChat = false
    private var chatSinceId = 0
    private var chatSinceAckAt: Double = 0

    private var issuesPollTask: Task<Void, Never>?
    private var devTaskPollTask: Task<Void, Never>?
    private var statsPollTask: Task<Void, Never>?
    private var fleetPollTask: Task<Void, Never>?
    private var deployPollTask: Task<Void, Never>?
    private var chatPollTask: Task<Void, Never>?
    private var issuesNextBeforeId: Int?
    private var devTasksNextBeforeId: Int?

    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "homeagent.dev.path")

    var activeBrainURL: String {
        brainEnvironment.activeBaseURL
    }

    init() {
        DevBrainEndpoint.migrateLegacyIfNeeded()
        lanDraft = DevBrainEndpoint.lanBaseURL
        cloudDraft = DevBrainEndpoint.cloudBaseURL
        brainRouting = DevBrainEndpoint.routing
        startPathMonitor()
        Task { await resolveBrainEndpoint() }
    }

    func saveConnection() {
        DevBrainEndpoint.lanBaseURL = lanDraft
        DevBrainEndpoint.cloudBaseURL = cloudDraft
        DevBrainEndpoint.routing = brainRouting
        DevSettings.adminToken = tokenDraft
        lanDraft = DevBrainEndpoint.lanBaseURL
        cloudDraft = DevBrainEndpoint.cloudBaseURL
        Task {
            await resolveBrainEndpoint()
            await reloadAllTabs()
        }
    }

    func applyBrainRouting(_ routing: DevBrainEndpoint.Routing) {
        brainRouting = routing
        DevBrainEndpoint.routing = routing
        Task {
            await resolveBrainEndpoint()
            await reloadAllTabs()
        }
    }

    func predictedBrainMode(for routing: DevBrainEndpoint.Routing) -> DevBrainEndpoint.Mode {
        switch routing {
        case .lan: return .lan
        case .cloud: return .cloud
        case .auto:
            return brainEnvironment.looksOnHomeLAN ? .lan : .cloud
        }
    }

    func predictedBrainBase(for routing: DevBrainEndpoint.Routing) -> String {
        predictedBrainMode(for: routing) == .lan
            ? DevBrainEndpoint.normalizeBase(lanDraft)
            : DevBrainEndpoint.normalizeBase(cloudDraft)
    }

    func resolveBrainEndpoint() async {
        while brainResolveBusy {
            try? await Task.sleep(nanoseconds: 80_000_000)
        }
        brainResolveBusy = true
        defer { brainResolveBusy = false }

        let routing = brainRouting
        let lan = DevBrainEndpoint.normalizeBase(lanDraft)
        let cloud = DevBrainEndpoint.normalizeBase(cloudDraft)
        let looksLAN = brainEnvironment.looksOnHomeLAN
        var probeOk: Bool?
        var probeDetail = ""

        let shouldProbeLAN = routing != .cloud && (looksLAN || routing == .lan)
        if shouldProbeLAN {
            let ok = await DevBrainProbe.ping(baseURL: lan)
            probeOk = ok
            probeDetail = ok ? "" : "局域网 Brain ping 失败（\(lan)）"
        } else if routing == .cloud {
            probeOk = nil
            probeDetail = "已强制走云 Brain，跳过 LAN 探测"
        } else {
            probeOk = false
            probeDetail = "当前不是家庭局域网，跳过 LAN 探测"
        }

        let useLAN: Bool
        switch routing {
        case .lan: useLAN = true
        case .cloud: useLAN = false
        case .auto: useLAN = probeOk == true
        }

        let next = useLAN ? lan : cloud
        brainEnvironment.routing = routing
        brainEnvironment.lanProbeOk = probeOk
        brainEnvironment.lanProbeDetail = probeDetail
        brainEnvironment.mode = useLAN ? .lan : .cloud
        brainEnvironment.activeBaseURL = next
        loadError = nil
    }

    private func reloadAllTabs() async {
        await loadIssues(reset: true, showSpinner: false)
        await loadDevTasks(reset: true, showSpinner: false)
        await loadStats(showSpinner: false)
        await loadFleet(showSpinner: false)
        await loadDeploy(showSpinner: false)
        await loadChat(reset: true, showSpinner: false)
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
        let kind: DevBrainPathKind
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
        let changed = looks != brainEnvironment.looksOnHomeLAN || kind != brainEnvironment.pathKind
        brainEnvironment.pathKind = kind
        brainEnvironment.looksOnHomeLAN = looks
        if changed {
            Task { await resolveBrainEndpoint() }
        }
    }

    func startIssuesPolling() {
        stopIssuesPolling()
        issuesPollTask = Task { [weak self] in
            await self?.resolveBrainEndpoint()
            await self?.loadIssues(reset: true, showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.refreshActiveIssues()
            }
        }
    }

    func stopIssuesPolling() {
        issuesPollTask?.cancel()
        issuesPollTask = nil
    }

    func startDevTaskPolling() {
        stopDevTaskPolling()
        devTaskPollTask = Task { [weak self] in
            await self?.resolveBrainEndpoint()
            await self?.loadDevTasks(reset: true, showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.refreshActiveDevTasks()
            }
        }
    }

    func startStatsPolling() {
        stopStatsPolling()
        statsPollTask = Task { [weak self] in
            await self?.resolveBrainEndpoint()
            await self?.loadStats(showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 10_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.loadStats(showSpinner: false)
            }
        }
    }

    func stopStatsPolling() {
        statsPollTask?.cancel()
        statsPollTask = nil
    }

    func startFleetPolling() {
        stopFleetPolling()
        fleetPollTask = Task { [weak self] in
            await self?.resolveBrainEndpoint()
            await self?.loadFleet(showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.loadFleet(showSpinner: false)
            }
        }
    }

    func stopFleetPolling() {
        fleetPollTask?.cancel()
        fleetPollTask = nil
    }

    func loadFleet(showSpinner: Bool = true) async {
        if showSpinner && fleetSnapshot == nil {
            isLoadingFleet = true
        }
        defer { isLoadingFleet = false }
        do {
            fleetSnapshot = try await DevClient.fetchFleet(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken
            )
            fleetError = nil
        } catch {
            fleetError = error.localizedDescription
        }
    }

    func wakeFleetAgent(handle: String, text: String = "") async {
        isWakingFleet = true
        defer { isWakingFleet = false }
        do {
            _ = try await DevClient.wakeFleetAgent(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                handle: handle,
                text: text
            )
            fleetError = nil
            await loadFleet(showSpinner: false)
        } catch {
            fleetError = error.localizedDescription
        }
    }

    func startDeployPolling() {
        stopDeployPolling()
        deployPollTask = Task { [weak self] in
            await self?.loadDeploy(showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.loadDeploy(showSpinner: false)
            }
        }
    }

    func stopDeployPolling() {
        deployPollTask?.cancel()
        deployPollTask = nil
    }

    func loadDeploy(showSpinner: Bool = true) async {
        if showSpinner && deploySnapshot == nil {
            isLoadingDeploy = true
        }
        defer { isLoadingDeploy = false }
        do {
            deploySnapshot = try await DevClient.fetchReleases(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken
            )
            deployError = nil
        } catch {
            deployError = error.localizedDescription
        }
    }

    func approveDeployRelease(releaseId: Int, note: String = "") async {
        isApprovingDeploy = true
        defer { isApprovingDeploy = false }
        do {
            _ = try await DevClient.approveRelease(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                releaseId: releaseId,
                note: note
            )
            deployError = nil
            await loadDeploy(showSpinner: false)
        } catch {
            deployError = error.localizedDescription
        }
    }

    func rejectDeployRelease(releaseId: Int, note: String = "") async {
        isApprovingDeploy = true
        defer { isApprovingDeploy = false }
        do {
            _ = try await DevClient.rejectRelease(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                releaseId: releaseId,
                note: note
            )
            deployError = nil
            await loadDeploy(showSpinner: false)
        } catch {
            deployError = error.localizedDescription
        }
    }

    func startChatPolling() {
        stopChatPolling()
        chatPollTask = Task { [weak self] in
            await self?.loadChat(reset: true, showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.loadChat(reset: false, showSpinner: false)
            }
        }
    }

    func stopChatPolling() {
        chatPollTask?.cancel()
        chatPollTask = nil
    }

    func loadChat(reset: Bool, showSpinner: Bool) async {
        if showSpinner && chatMessages.isEmpty {
            isLoadingChat = true
        }
        defer { isLoadingChat = false }
        do {
            if reset {
                chatSinceId = 0
            }
            let snap = try await DevClient.fetchAgentChat(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                sinceId: chatSinceId,
                sinceAckAt: chatSinceAckAt
            )
            if reset {
                chatMessages = snap.messages.sorted { $0.id < $1.id }
            } else {
                mergeChatMessages(snap.messages)
            }
            applyAckPatches(snap.ackPatches)
            if let last = chatMessages.map(\.id).max() {
                chatSinceId = last
            }
            if let latest = snap.latestAckAt, latest > chatSinceAckAt {
                chatSinceAckAt = latest
            }
            chatError = nil
            if snap.chatOk == false, let err = snap.error, !err.isEmpty {
                chatError = err
            }
        } catch {
            chatError = error.localizedDescription
        }
    }

    func sendChatMessage(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isSendingChat = true
        defer { isSendingChat = false }
        let pendingId = -(Int(Date().timeIntervalSince1970 * 1000) % 1_000_000_000)
        let pending = AgentChatMessage.pendingBoss(body: trimmed, id: pendingId)
        chatMessages.append(pending)
        do {
            let sent = try await DevClient.sendAgentChatMessage(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                body: trimmed
            )
            chatMessages.removeAll { $0.id == pendingId }
            mergeChatMessages([sent])
            chatSinceId = max(chatSinceId, sent.id)
            chatError = nil
        } catch {
            chatMessages.removeAll { $0.id == pendingId }
            chatError = error.localizedDescription
        }
    }

    func ackChatMessage(_ messageId: Int) async {
        guard messageId > 0 else { return }
        do {
            let updated = try await DevClient.ackAgentChatMessage(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                messageId: messageId
            )
            mergeChatMessages([updated])
            chatSinceAckAt = max(chatSinceAckAt, Date().timeIntervalSince1970)
            chatError = nil
        } catch {
            chatError = error.localizedDescription
        }
    }

    func unackChatMessage(_ messageId: Int) async {
        guard messageId > 0 else { return }
        do {
            let updated = try await DevClient.unackAgentChatMessage(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                messageId: messageId
            )
            mergeChatMessages([updated])
            chatSinceAckAt = max(chatSinceAckAt, Date().timeIntervalSince1970)
            chatError = nil
        } catch {
            chatError = error.localizedDescription
        }
    }

    func promoteChatToDevTask(
        text: String,
        targetHandle: String,
        category: String,
        anchorMessageId: Int,
        backgroundMessageIds: [Int]
    ) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            _ = try await DevClient.promoteAgentChat(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                text: trimmed,
                targetHandle: targetHandle,
                category: category,
                anchorMessageId: anchorMessageId,
                backgroundMessageIds: backgroundMessageIds
            )
            chatError = nil
            await loadDevTasks(reset: true, showSpinner: false)
        } catch {
            chatError = error.localizedDescription
        }
    }

    private func mergeChatMessages(_ incoming: [AgentChatMessage]) {
        guard !incoming.isEmpty else { return }
        var byId = Dictionary(uniqueKeysWithValues: chatMessages.map { ($0.id, $0) })
        for row in incoming {
            byId[row.id] = row
        }
        chatMessages = byId.values.sorted { $0.id < $1.id }
    }

    private func applyAckPatches(_ patches: [AgentChatAckPatch]) {
        guard !patches.isEmpty else { return }
        var byId = Dictionary(uniqueKeysWithValues: chatMessages.map { ($0.id, $0) })
        for patch in patches {
            guard var existing = byId[patch.id] else { continue }
            existing = AgentChatMessage(
                id: existing.id,
                fromHandle: existing.fromHandle,
                body: existing.body,
                kind: existing.kind,
                replyToId: existing.replyToId,
                createdAt: existing.createdAt,
                timestampLabel: existing.timestampLabel,
                mentions: existing.mentions,
                audience: existing.audience,
                recalled: existing.recalled,
                isPending: existing.isPending,
                acks: patch.acks
            )
            byId[patch.id] = existing
        }
        chatMessages = byId.values.sorted { $0.id < $1.id }
    }

    func loadStats(showSpinner: Bool = true) async {
        if showSpinner && statsUsage == nil {
            isLoadingStats = true
        }
        defer { isLoadingStats = false }
        do {
            statsUsage = try await DevClient.fetchDevTaskUsage(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                period: statsPeriod
            )
            statsError = nil
        } catch {
            statsError = error.localizedDescription
        }
    }

    func stopDevTaskPolling() {
        devTaskPollTask?.cancel()
        devTaskPollTask = nil
    }

    func loadIssues(reset: Bool, showSpinner: Bool) async {
        if showSpinner && (reset || issues.isEmpty) {
            isLoadingIssues = true
        }
        defer { isLoadingIssues = false }
        do {
            let before = reset ? nil : issuesNextBeforeId
            let page = try await DevClient.fetchIssues(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                limit: 30,
                beforeId: before
            )
            if reset {
                mergeIssueFirstPage(page.issues)
                issuesNextBeforeId = page.nextBeforeId
            } else {
                let existing = Set(issues.map(\.issueId))
                let extra = page.issues.filter { !existing.contains($0.issueId) }
                issues.append(contentsOf: extra)
                issues.sort { $0.issueId > $1.issueId }
                if let next = page.nextBeforeId {
                    issuesNextBeforeId = next
                }
            }
            issuesExhausted = page.exhausted == true || page.issues.isEmpty
            issuesError = nil
        } catch {
            issuesError = error.localizedDescription
        }
    }

    func refreshActiveIssues() async {
        let active = issues.filter(\.isActive).map(\.issueId)
        guard !active.isEmpty else { return }
        for issueId in active {
            do {
                let fresh = try await DevClient.fetchIssue(
                    brainURL: activeBrainURL,
                    token: DevSettings.adminToken,
                    issueId: issueId
                )
                if let idx = issues.firstIndex(where: { $0.issueId == issueId }) {
                    issues[idx] = fresh
                } else {
                    issues.insert(fresh, at: 0)
                }
            } catch {
                issuesError = error.localizedDescription
            }
        }
    }

    private func mergeIssueFirstPage(_ fetched: [DebugIssue]) {
        let fetchedIds = Set(fetched.map(\.issueId))
        let oldest = fetched.map(\.issueId).min() ?? Int.max
        let older = issues.filter { $0.issueId < oldest && !fetchedIds.contains($0.issueId) }
        issues = (fetched + older).sorted { $0.issueId > $1.issueId }
    }

    func loadDevTasks(reset: Bool, showSpinner: Bool) async {
        if showSpinner && (reset || devTasks.isEmpty) {
            isLoadingDevTasks = true
        }
        defer { isLoadingDevTasks = false }
        do {
            let before = reset ? nil : devTasksNextBeforeId
            let page = try await DevClient.fetchDevTasks(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                limit: 30,
                beforeId: before,
                category: devTaskCategoryFilter.isEmpty ? nil : devTaskCategoryFilter
            )
            if reset {
                mergeDevTaskFirstPage(page.tasks)
                devTasksNextBeforeId = page.nextBeforeId
            } else {
                let existing = Set(devTasks.map(\.taskId))
                let extra = page.tasks.filter { !existing.contains($0.taskId) }
                devTasks.append(contentsOf: extra)
                devTasks.sort { $0.taskId > $1.taskId }
                if let next = page.nextBeforeId {
                    devTasksNextBeforeId = next
                }
            }
            devTasksExhausted = page.exhausted == true || page.tasks.isEmpty
            devTasksError = nil
        } catch {
            devTasksError = error.localizedDescription
        }
    }

    @discardableResult
    func sendDevTask(
        text: String? = nil,
        category: String? = nil,
        continueTaskId: Int? = nil,
        pendingAttachments: [PendingDevAttachment] = []
    ) async -> DevTask? {
        let trimmed = (text ?? devTaskDraft).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !pendingAttachments.isEmpty else { return nil }
        let chosenCategory = category ?? devTaskCategory
        isSendingDevTask = true
        defer { isSendingDevTask = false }
        do {
            let uploaded = try await uploadPendingAttachments(pendingAttachments)
            let task = try await DevClient.submitDevTask(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                text: trimmed,
                continueTaskId: continueTaskId,
                category: continueTaskId == nil ? chosenCategory : nil,
                attachments: uploaded
            )
            if text == nil {
                devTaskDraft = ""
            }
            if continueTaskId == nil {
                devTasks.removeAll { $0.taskId == task.taskId }
                devTasks.insert(task, at: 0)
            }
            devTasksError = nil
            return task
        } catch {
            devTasksError = error.localizedDescription
            return nil
        }
    }

    @discardableResult
    func sendDevTask(continueTaskId: Int? = nil) async -> DevTask? {
        await sendDevTask(text: nil, category: nil, continueTaskId: continueTaskId)
    }

    func sendDevTaskFollowUp(
        threadRootTaskId: Int,
        text: String,
        pendingAttachments: [PendingDevAttachment] = []
    ) async -> DevTask? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !pendingAttachments.isEmpty else { return nil }
        isSendingDevTask = true
        defer { isSendingDevTask = false }
        do {
            let uploaded = try await uploadPendingAttachments(pendingAttachments)
            let task = try await DevClient.submitDevTask(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                text: trimmed,
                continueTaskId: threadRootTaskId,
                attachments: uploaded
            )
            devTasksError = nil
            return task
        } catch {
            devTasksError = error.localizedDescription
            return nil
        }
    }

    func setDevTaskCategoryFilter(_ category: String) async {
        devTaskCategoryFilter = category
        await loadDevTasks(reset: true, showSpinner: true)
    }

    func updateThreadCategory(taskId: Int, category: String) async -> DevTask? {
        do {
            let task = try await DevClient.patchDevTaskCategory(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                taskId: taskId,
                category: category
            )
            let rootId = task.threadId
            if let idx = devTasks.firstIndex(where: { $0.taskId == rootId }) {
                devTasks[idx] = task
            }
            devTasksError = nil
            return task
        } catch {
            devTasksError = error.localizedDescription
            return nil
        }
    }

    func fetchDevTask(taskId: Int) async -> DevTask? {
        do {
            return try await DevClient.fetchDevTask(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                taskId: taskId
            )
        } catch {
            devTasksError = error.localizedDescription
            return nil
        }
    }

    @discardableResult
    func cancelDevTask(taskId: Int) async -> DevTask? {
        isCancellingDevTask = true
        defer { isCancellingDevTask = false }
        do {
            let task = try await DevClient.cancelDevTask(
                brainURL: activeBrainURL,
                token: DevSettings.adminToken,
                taskId: taskId
            )
            if let idx = devTasks.firstIndex(where: { $0.taskId == task.threadId }) {
                devTasks[idx] = task
            } else if let idx = devTasks.firstIndex(where: { $0.taskId == task.taskId }) {
                devTasks[idx] = task
            }
            devTasksError = nil
            return task
        } catch {
            devTasksError = error.localizedDescription
            return nil
        }
    }

    func refreshActiveDevTasks() async {
        let activeIds = devTasks.filter(\.isActive).map(\.taskId)
        guard !activeIds.isEmpty else { return }
        for taskId in activeIds {
            do {
                let fresh = try await DevClient.fetchDevTask(
                    brainURL: activeBrainURL,
                    token: DevSettings.adminToken,
                    taskId: taskId
                )
                if let idx = devTasks.firstIndex(where: { $0.taskId == taskId }) {
                    devTasks[idx] = fresh
                } else {
                    devTasks.insert(fresh, at: 0)
                }
            } catch {
                devTasksError = error.localizedDescription
            }
        }
    }

    private func mergeDevTaskFirstPage(_ fetched: [DevTask]) {
        let fetchedIds = Set(fetched.map(\.taskId))
        let oldest = fetched.map(\.taskId).min() ?? Int.max
        let older = devTasks.filter { $0.taskId < oldest && !fetchedIds.contains($0.taskId) }
        devTasks = (fetched + older).sorted { $0.taskId > $1.taskId }
    }

    private func uploadPendingAttachments(_ pending: [PendingDevAttachment]) async throws -> [DebugAttachment] {
        guard !pending.isEmpty else { return [] }
        var uploaded: [DebugAttachment] = []
        for item in pending {
            let row = try await DevAttachmentUpload.upload(
                item,
                brainURL: activeBrainURL,
                token: DevSettings.adminToken
            )
            uploaded.append(row)
        }
        return uploaded
    }
}
