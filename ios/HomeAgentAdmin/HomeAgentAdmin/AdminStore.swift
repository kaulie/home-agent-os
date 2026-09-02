import Foundation

@MainActor
final class AdminStore: ObservableObject {
    @Published var nodes: [AdminNode] = []
    @Published var filter: OnlineFilter = .online
    @Published var loadError: String?
    @Published var isLoading = false
    @Published var pendingDisable: PendingDisable?

    @Published var brainDraft: String = AdminSettings.brainURL
    @Published var tokenDraft: String = AdminSettings.adminToken
    @Published private(set) var busyKeys: Set<String> = []
    @Published private(set) var logs: [AdminLogEntry] = AdminSettings.loadLogs()
    @Published private(set) var logsFromBrain = false
    @Published var logsBanner: String?
    @Published private(set) var intents: [AdminIntent] = []
    @Published var intentsError: String?
    @Published var intentsExhausted = false
    @Published var isLoadingIntents = false
    private var pollTask: Task<Void, Never>?
    private var intentPollTask: Task<Void, Never>?
    private var intentsNextBeforeId: Int?

    func discoverLanBrain() async {
        await AdminSettings.autoDiscoverBrain()
        brainDraft = AdminSettings.brainURL
        await load(showSpinner: true)
    }

    var filteredNodes: [AdminNode] {
        nodes.filter { $0.onlineStatus == filter.rawValue }
            .sorted { lhs, rhs in
                if lhs.isOnline != rhs.isOnline { return lhs.isOnline }
                return lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
            }
    }

    var onlineCount: Int { nodes.filter(\.isOnline).count }

    func node(id: String) -> AdminNode? {
        nodes.first { $0.participantId == id }
    }

    func isBusy(_ key: String) -> Bool {
        busyKeys.contains(key)
    }

    func load(showSpinner: Bool) async {
        if showSpinner { isLoading = true }
        defer { if showSpinner { isLoading = false } }
        do {
            let fetched = try await AdminClient.fetchNodes(
                brainURL: AdminSettings.brainURL,
                token: AdminSettings.adminToken
            )
            nodes = fetched
            loadError = nil
            await refreshLogs()
        } catch {
            loadError = error.localizedDescription
        }
    }

    func saveConnectionAndRefresh() async {
        AdminSettings.brainURL = brainDraft
        AdminSettings.adminToken = tokenDraft
        brainDraft = AdminSettings.brainURL
        await load(showSpinner: true)
        if logsFromBrain {
            return
        }
        if let err = loadError, !err.isEmpty {
            appendLocalLog(kind: .error, summary: "保存 Brain 后刷新失败：\(err)")
        } else {
            appendLocalLog(
                kind: .connection,
                summary: "保存 Brain \(AdminSettings.brainURL) · 刷新 \(nodes.count) 个节点"
            )
        }
    }

    func requestToggle(
        participantId: String,
        kind: PolicyTargetKind,
        targetId: String,
        title: String,
        enabled: Bool
    ) {
        if enabled {
            Task {
                await applyPolicy(
                    participantId: participantId,
                    kind: kind,
                    targetId: targetId,
                    title: title,
                    enabled: true
                )
            }
            return
        }
        pendingDisable = PendingDisable(
            participantId: participantId,
            kind: kind,
            targetId: targetId,
            title: title
        )
    }

    func confirmPendingDisable() async {
        guard let pending = pendingDisable else { return }
        pendingDisable = nil
        await applyPolicy(
            participantId: pending.participantId,
            kind: pending.kind,
            targetId: pending.targetId,
            title: pending.title,
            enabled: false
        )
    }

    func cancelPendingDisable() {
        pendingDisable = nil
    }

    func startPolling() {
        stopPolling()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.silentRefresh()
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func startIntentPolling() {
        stopIntentPolling()
        intentPollTask = Task { [weak self] in
            await self?.loadIntents(reset: true, showSpinner: true)
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                guard !Task.isCancelled else { return }
                await self?.loadIntents(reset: true, showSpinner: false)
            }
        }
    }

    func stopIntentPolling() {
        intentPollTask?.cancel()
        intentPollTask = nil
    }

    func loadIntents(reset: Bool, showSpinner: Bool) async {
        if showSpinner && (reset || intents.isEmpty) {
            isLoadingIntents = true
        }
        defer { isLoadingIntents = false }
        do {
            let before = reset ? nil : intentsNextBeforeId
            let page = try await AdminClient.fetchIntents(
                brainURL: AdminSettings.brainURL,
                token: AdminSettings.adminToken,
                limit: 50,
                beforeId: before
            )
            if reset {
                mergeFirstPage(page.intents)
                intentsNextBeforeId = page.nextBeforeId
            } else {
                let existing = Set(intents.map(\.intentId))
                let extra = page.intents.filter { !existing.contains($0.intentId) }
                intents.append(contentsOf: extra)
                intents.sort { $0.intentId > $1.intentId }
                if let next = page.nextBeforeId {
                    intentsNextBeforeId = next
                }
            }
            intentsExhausted = page.exhausted == true || page.intents.isEmpty
            intentsError = nil
        } catch {
            intentsError = error.localizedDescription
        }
    }

    private func mergeFirstPage(_ fetched: [AdminIntent]) {
        let fetchedIds = Set(fetched.map(\.intentId))
        let oldestFetched = fetched.map(\.intentId).min() ?? Int.max
        let older = intents.filter { $0.intentId < oldestFetched && !fetchedIds.contains($0.intentId) }
        intents = (fetched + older).sorted { $0.intentId > $1.intentId }
    }

    private func silentRefresh() async {
        guard busyKeys.isEmpty, pendingDisable == nil else { return }
        do {
            let fetched = try await AdminClient.fetchNodes(
                brainURL: AdminSettings.brainURL,
                token: AdminSettings.adminToken
            )
            nodes = fetched
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    func clearLogs() {
        guard !logsFromBrain else { return }
        logs = []
        AdminSettings.saveLogs(logs)
    }

    func refreshLogs() async {
        do {
            let fetched = try await AdminClient.fetchLogs(
                brainURL: AdminSettings.brainURL,
                token: AdminSettings.adminToken
            )
            logs = fetched
            logsFromBrain = true
            logsBanner = nil
        } catch AdminClientError.missingLogs {
            logsFromBrain = false
            logsBanner = "Brain 还没有操作日志接口，暂时只看本机记录。"
            logs = AdminSettings.loadLogs()
        } catch {
            logsBanner = "操作日志刷新失败：\(error.localizedDescription)"
            if !logsFromBrain {
                logs = AdminSettings.loadLogs()
            }
        }
    }

    private func applyPolicy(
        participantId: String,
        kind: PolicyTargetKind,
        targetId: String,
        title: String,
        enabled: Bool
    ) async {
        let key = "\(participantId)|\(kind.rawValue)|\(targetId)"
        busyKeys.insert(key)
        defer { busyKeys.remove(key) }
        let nodeTitle = node(id: participantId)?.title ?? participantId
        let verb = enabled ? "打开" : "关掉"
        let summary = "\(verb) \(nodeTitle) 的 \(title)"
        do {
            try await AdminClient.setPolicy(
                brainURL: AdminSettings.brainURL,
                token: AdminSettings.adminToken,
                participantId: participantId,
                kind: kind,
                targetId: targetId,
                enabled: enabled
            )
            await load(showSpinner: false)
            if !logsFromBrain {
                appendLocalLog(kind: .policy, summary: summary)
            }
        } catch {
            loadError = error.localizedDescription
            await refreshLogs()
            if !logsFromBrain {
                appendLocalLog(kind: .error, summary: "\(summary) 失败：\(error.localizedDescription)")
            }
        }
    }

    private func appendLocalLog(kind: AdminLogKind, summary: String) {
        let entry = AdminLogEntry(id: UUID().uuidString, at: Date(), kind: kind, summary: summary)
        logs.insert(entry, at: 0)
        if logs.count > 200 {
            logs = Array(logs.prefix(200))
        }
        AdminSettings.saveLogs(logs)
    }
}
