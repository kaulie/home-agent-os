import Foundation

@MainActor
protocol EdgeAgentListener: AnyObject {
    func onStatus(_ message: String)
    func onPlansFetched(_ plans: [Plan])
    func onPlanFinished(_ outcome: PlanOutcome)
    func onReport(_ report: ExecutionReport)
    func onEdgeInfoReported(_ info: EdgeNodeInfo)
    func onEdgeIdAssigned(_ edgeId: String)
}

extension EdgeAgentListener {
    func onEdgeInfoReported(_ info: EdgeNodeInfo) {}
    func onEdgeIdAssigned(_ edgeId: String) {}
}

/// Supplies live health for edge → brain reports.
@MainActor
protocol EdgeHealthProviding: AnyObject {
    func currentEdgeHealth() -> EdgeHealthSnapshot
}

/// Living-room Edge runtime.
///
/// Two independent registration paths:
/// - **Capability plugins → Edge** (`installCapability`): local plugin registry.
/// - **Edge → Brain**: first `registerEdge` (Brain issues `edgeId`), then heartbeat
///   with that `edgeId` via `reportEdgeInfo`.
@MainActor
final class EdgeAgent: ObservableObject {
    let identity: EdgeIdentity

    /// Brain-issued edge id (nil until register succeeds or a persisted id is loaded).
    @Published private(set) var assignedEdgeId: String?

    /// Effective id for plans / heartbeat: assigned if present, else local clientHint.
    var edgeId: String { assignedEdgeId ?? identity.clientHint }

    private let brain: BrainClient
    let capabilityRegistry: CapabilityRegistry
    private let skillRegistry: SkillRegistry
    private let heartbeatIntervalNs: UInt64
    private let executor: PlanExecutor
    private let commandSource: HttpCommandSource
    private let commandHandler: CommandHandler
    private let localRuntime: LocalEdgeRuntime
    private let intentScheduler: IntentScheduler?
    private let intentStepExecutor: IntentStepExecutor?

    private var loopTask: Task<Void, Never>?
    /// Long skill work (camera/cast) must not sit inside the heartbeat tick.
    private var commandWorkTask: Task<Void, Never>?
    private var commandBusy = false
    private var tickLock = false

    @Published private(set) var running = false
    @Published private(set) var lastReportedInfo: EdgeNodeInfo?
    /// When false, tick still heartbeats / runs local plans, but skips server command pull (UI debug).
    @Published private(set) var serverCommandPollingEnabled = true

    weak var listener: EdgeAgentListener?
    weak var healthProvider: EdgeHealthProviding?

    init(
        identity: EdgeIdentity,
        brain: BrainClient,
        capabilityRegistry: CapabilityRegistry = CapabilityRegistry(),
        skillRegistry: SkillRegistry = SkillRegistry(),
        heartbeatIntervalMs: UInt64 = 5000,
        commandSource: HttpCommandSource = HttpCommandSource(),
        commandHandler: CommandHandler? = nil,
        localRuntime: LocalEdgeRuntime? = nil,
        intentController: IntentController? = nil
    ) {
        self.identity = identity
        self.brain = brain
        self.capabilityRegistry = capabilityRegistry
        self.skillRegistry = skillRegistry
        self.heartbeatIntervalNs = heartbeatIntervalMs * 1_000_000
        // Reuse Brain-issued edge_id from local file across launches.
        let initialAssigned = EdgeIdStore.load()
        self.assignedEdgeId = initialAssigned
        self.executor = PlanExecutor(
            edgeId: initialAssigned ?? identity.clientHint,
            registry: skillRegistry,
            brain: brain
        )
        self.commandSource = commandSource
        if let initialAssigned {
            commandSource.localEdgeId = initialAssigned
        }
        let runtime = localRuntime ?? LocalEdgeRuntime(
            edgeId: initialAssigned ?? identity.clientHint,
            registry: skillRegistry,
            brain: brain,
            intentController: intentController
        )
        self.localRuntime = runtime
        let node = EdgeRuntimeNode(
            nodeId: initialAssigned ?? identity.clientHint,
            displayName: identity.displayName
        )
        let handler = commandHandler ?? CommandHandler(
            dispatcher: LocalTaskDispatcher(runtime: runtime),
            localNode: node,
            intentController: intentController
        )
        self.commandHandler = handler
        if let intentController {
            self.intentScheduler = IntentScheduler(intentController: intentController)
            self.intentStepExecutor = IntentStepExecutor(
                commandHandler: handler,
                intentController: intentController
            )
        } else {
            self.intentScheduler = nil
            self.intentStepExecutor = nil
        }
        // Closures capture self only after all stored properties are initialized.
        self.commandHandler.onLog = { [weak self] msg in
            self?.postStatus(msg)
        }
        self.intentScheduler?.onLog = { [weak self] msg in self?.postStatus(msg) }
        self.intentStepExecutor?.onLog = { [weak self] msg in self?.postStatus(msg) }
    }

    convenience init(
        edgeId: String,
        brain: BrainClient,
        registry: SkillRegistry,
        heartbeatIntervalMs: UInt64 = 5000,
        displayName: String? = nil,
        deviceType: EdgeDeviceType = .other
    ) {
        self.init(
            identity: EdgeIdentity(
                edgeId: edgeId,
                displayName: displayName ?? edgeId,
                deviceType: deviceType
            ),
            brain: brain,
            skillRegistry: registry,
            heartbeatIntervalMs: heartbeatIntervalMs
        )
    }

    // MARK: - Capability plugins → Edge (local)

    func installCapability(_ plugin: CapabilityPlugin) {
        capabilityRegistry.register(plugin)
        rebuildSkillRegistryFromCapabilities()
        postStatus("Capability plugin registered: \(plugin.capabilityId)")
    }

    func installCapabilities(_ plugins: [CapabilityPlugin]) {
        plugins.forEach { capabilityRegistry.register($0) }
        rebuildSkillRegistryFromCapabilities()
        postStatus("Capability plugins registered: \(capabilityRegistry.capabilityIds().joined(separator: ", "))")
    }

    func installSkills(_ skills: [Skill]) {
        skillRegistry.registerAll(skills)
    }

    private func rebuildSkillRegistryFromCapabilities() {
        skillRegistry.replaceAll(capabilityRegistry.makeSkills())
    }

    // MARK: - Edge → Brain (register then heartbeat)

    func start() {
        guard !running else { return }
        running = true
        postStatus(
            "EdgeAgent starting hint=\(identity.clientHint) device=\(identity.deviceType.rawValue)"
                + (assignedEdgeId.map { " assigned=\($0)" } ?? " (need register)")
        )
        loopTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await self.ensureRegisteredWithBrain()
                let info = self.buildNodeInfo(online: .online)
                try await self.brain.reportEdgeInfo(info)
                self.lastReportedInfo = info
                self.listener?.onEdgeInfoReported(info)
                self.postStatus(
                    "Heartbeat ok edgeId=\(info.edgeId) services=\(info.services.count) caps=\(info.services.reduce(0) { $0 + $1.capabilities.count })"
                )
            } catch {
                let ns = error as NSError
                if ns.domain == "HttpEdgeReporter", ns.code == 401 {
                    self.clearAssignedEdgeId()
                    self.postStatus("Brain 不认可 edgeId，已清除，将重新 register")
                } else {
                    self.postStatus("Brain register/heartbeat failed: \(error.localizedDescription)")
                }
            }
            while !Task.isCancelled && self.running {
                await self.tick()
                try? await Task.sleep(nanoseconds: self.heartbeatIntervalNs)
            }
        }
    }

    func stop() {
        let wasRunning = running
        running = false
        loopTask?.cancel()
        loopTask = nil
        commandWorkTask?.cancel()
        commandWorkTask = nil
        commandBusy = false
        if wasRunning, assignedEdgeId != nil {
            Task { [weak self] in
                guard let self else { return }
                let info = self.buildNodeInfo(online: .offline)
                try? await self.brain.reportEdgeInfo(info)
                self.lastReportedInfo = info
                self.listener?.onEdgeInfoReported(info)
                self.postStatus("EdgeAgent stopped (reported offline to Brain)")
            }
        } else {
            postStatus("EdgeAgent stopped")
        }
    }

    func pollNow() {
        Task { await tick() }
    }

    /// Debug: stop Agent from auto-pulling server intents (heartbeat continues).
    func stopServerCommandPolling() {
        guard serverCommandPollingEnabled else { return }
        serverCommandPollingEnabled = false
        postStatus("已停止后端 intents 轮询（心跳仍继续；可用前端手动拉取调试）")
    }

    /// Debug: resume Agent auto-pull of server intents.
    func startServerCommandPolling() {
        guard !serverCommandPollingEnabled else { return }
        serverCommandPollingEnabled = true
        postStatus("已恢复后端 intents 轮询（间隔随 Agent tick）")
    }

    func setServerCommandPollingEnabled(_ enabled: Bool) {
        if enabled {
            startServerCommandPolling()
        } else {
            stopServerCommandPolling()
        }
    }

    /// Clear persisted Brain-issued id (force re-register next start).
    func clearAssignedEdgeId() {
        assignedEdgeId = nil
        EdgeIdStore.clear()
        commandSource.localEdgeId = nil
        executor.edgeId = identity.clientHint
        localRuntime.updateEdgeId(identity.clientHint)
        postStatus("Cleared assigned edgeId (file); next start will re-register")
    }

    /// Adopt a Brain-issued edgeId from a manual debug register call.
    func adoptAssignedEdgeId(_ id: String) {
        let trimmed = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        applyAssignedEdgeId(trimmed)
        postStatus("Adopted Brain edgeId=\(trimmed) (saved to local file)")
    }

    /// Whether a Brain-issued edge_id is already cached locally.
    var hasCachedEdgeId: Bool {
        !(assignedEdgeId ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func ensureRegisteredWithBrain() async throws {
        // Already registered before → reuse local file edge_id, do not call /edge-register again.
        if let existing = assignedEdgeId?.trimmingCharacters(in: .whitespacesAndNewlines), !existing.isEmpty {
            executor.edgeId = existing
            localRuntime.updateEdgeId(existing)
            commandSource.localEdgeId = existing
            postStatus("Reuse cached edge_id=\(existing) (skip register)")
            return
        }
        // Also re-read file in case another path wrote it.
        if let fromFile = EdgeIdStore.load(), !fromFile.isEmpty {
            applyAssignedEdgeId(fromFile)
            postStatus("Loaded edge_id=\(fromFile) from local file (skip register)")
            return
        }

        let request = EdgeRegisterRequest(
            clientHint: identity.clientHint,
            displayName: identity.displayName,
            deviceType: identity.deviceType,
            room: identity.room,
            services: servicesForBrain(),
            appVersion: identity.appVersion
        )
        postStatus("No cached edge_id — registering with Brain…")
        let response = try await brain.registerEdge(request)
        guard response.isApproved else {
            let detail = response.message.isEmpty ? response.status : response.message
            throw NSError(
                domain: "EdgeAgent",
                code: 1,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "Brain register \(response.status.isEmpty ? "failed" : response.status): \(detail)",
                ]
            )
        }
        let id = response.edgeId
        applyAssignedEdgeId(id)
        postStatus("Brain assigned edgeId=\(id) status=\(response.status) (saved to local file)")
    }

    private func applyAssignedEdgeId(_ id: String) {
        assignedEdgeId = id
        EdgeIdStore.save(id)
        executor.edgeId = id
        localRuntime.updateEdgeId(id)
        commandSource.localEdgeId = id
        listener?.onEdgeIdAssigned(id)
    }

    /// Snapshot for Brain heartbeat: must use Brain-issued `edgeId` when available.
    func buildNodeInfo(online: EdgeOnlineStatus) -> EdgeNodeInfo {
        let health: EdgeHealthSnapshot
        if online == .offline {
            health = EdgeHealthSnapshot(status: .unknown, summary: "agent stopped", details: [:])
        } else if let provider = healthProvider {
            health = provider.currentEdgeHealth()
        } else {
            health = EdgeHealthSnapshot(
                status: running ? .healthy : .unknown,
                summary: running ? "agent running" : "agent idle",
                details: [:]
            )
        }
        return EdgeNodeInfo(
            edgeId: edgeId,
            displayName: identity.displayName,
            deviceType: identity.deviceType,
            room: identity.room,
            onlineStatus: online,
            health: health,
            services: servicesForBrain(),
            appVersion: identity.appVersion
        )
    }

    /// Temporarily do not advertise Cast to Brain (Mac Edge owns display.photo for now).
    /// Skill code / UI remain installed locally — flip to `true` to resume advertising.
    static let advertiseChromecastDisplayToBrain = false

    /// Services advertised to Brain: device plugins only (exclude local system helpers).
    func servicesForBrain() -> [ServiceDescriptor] {
        skillRegistry.services().filter { svc in
            if !Self.advertiseChromecastDisplayToBrain,
               svc.serviceId == ChromecastCastSkill.skillId
            {
                return false
            }
            return svc.group != "system"
                && svc.serviceId != IntentSkill.skillId
                && svc.serviceId != CommandSkill.skillId
        }
    }

    private func tick() async {
        if tickLock { return }
        tickLock = true
        defer { tickLock = false }
        do {
            if assignedEdgeId == nil {
                try await ensureRegisteredWithBrain()
            }
            localRuntime.updateEdgeId(edgeId)
            executor.edgeId = edgeId
            let info = buildNodeInfo(online: .online)
            try await brain.reportEdgeInfo(info)
            lastReportedInfo = info
            listener?.onEdgeInfoReported(info)
            postStatus(
                "Heartbeat ok edgeId=\(info.edgeId) services=\(info.services.count) caps=\(info.services.reduce(0) { $0 + $1.capabilities.count })"
            )

            // Local plans first (intent.dispatch). Pull used to run first and set
            // commandBusy asynchronously, which starved dispatch and left UI on「发出中」.
            await handleLocalPlans()
            await pullAndHandleServerCommands()
        } catch {
            let ns = error as NSError
            if ns.domain == "HttpEdgeReporter", ns.code == 401 {
                clearAssignedEdgeId()
                postStatus("Brain 不认可 edgeId，已清除，下轮将重新 register")
            } else {
                postStatus("Tick failed: \(error.localizedDescription)")
            }
        }
    }

    private func pullAndHandleServerCommands() async {
        guard serverCommandPollingEnabled else {
            postStatus("Intents pull: skipped (disabled)")
            return
        }
        // Never block heartbeat on camera/cast; skip consume while work is in flight.
        if commandBusy {
            postStatus("Intents pull: deferred (execution in progress)")
            return
        }
        do {
            commandSource.localEdgeId = edgeId
            // Peek (not pop): multi-tick / multi-edge need the same intent until terminal.
            // Brain drops succeeded/failed from the queue; Edge also ignores terminals.
            let intents = try await commandSource.fetchIntents(consume: false)
            if intents.isEmpty {
                postStatus("Intents pull: empty (edgeId=\(edgeId); UI 排队=已 dispatch 但本轮未领到可执行 step)")
                return
            }
            postStatus(
                "Pulled \(intents.count) intent(s) edgeId=\(edgeId) → scheduler then step executor"
            )
            enqueueIntentWork(intents)
        } catch {
            postStatus("Intents pull failed: \(error.localizedDescription)")
        }
    }

    /// Tick order: IntentScheduler → IntentStepExecutor (same node may be both).
    private func enqueueIntentWork(_ intents: [[String: Any]]) {
        commandBusy = true
        commandWorkTask = Task { [weak self] in
            guard let self else { return }
            defer {
                Task { @MainActor [weak self] in
                    self?.commandBusy = false
                    self?.commandWorkTask = nil
                }
            }
            let eid = await MainActor.run { self.edgeId }
            for (idx, intent) in intents.enumerated() {
                let iid = (intent["id"] as? String)
                    ?? (intent["intent_id"] as? String)
                    ?? String(describing: intent["id"] ?? idx)
                await MainActor.run {
                    self.postStatus("Intent[\(idx + 1)/\(intents.count)] \(iid) → scheduler")
                }
                await self.intentScheduler?.handle(intent: intent, localEdgeId: eid)
                await MainActor.run {
                    self.postStatus("Intent[\(idx + 1)/\(intents.count)] \(iid) → step executor")
                }
                await self.intentStepExecutor?.handle(intent: intent, localEdgeId: eid)
            }
            await MainActor.run {
                self.postStatus("Intent pipeline done: \(intents.count) intent(s)")
            }
        }
    }

    private func handleLocalPlans() async {
        do {
            let plans = try await brain.fetchPlans(edgeId: edgeId)
            guard !plans.isEmpty else { return }
            listener?.onPlansFetched(plans)
            // Await inline (do not gate on commandBusy): intent.dispatch must finish so
            // the「发出指令」button can leave「发出中」even while a server intent is running.
            for plan in plans {
                postStatus(
                    "Plan \(plan.planId) → CommandHandler (\(plan.steps.count) steps)"
                )
                let commands = CommandDecomposer.fromPlan(plan)
                let results = await commandHandler.handle(commands)
                let reports: [ExecutionReport] = results.map { r in
                    ExecutionReport(
                        planId: plan.planId,
                        stepId: r.taskId,
                        status: r.skipped ? .skipped : (r.ok ? .ok : .error),
                        message: r.message
                    )
                }
                let aborted = results.contains { !$0.ok && !$0.skipped }
                await MainActor.run {
                    reports.forEach { self.listener?.onReport($0) }
                    self.listener?.onPlanFinished(
                        PlanOutcome(planId: plan.planId, reports: reports, aborted: aborted)
                    )
                }
            }
        } catch {
            postStatus("Local plans failed: \(error.localizedDescription)")
        }
    }

    /// Run CommandHandler off the heartbeat loop so 15s ticks keep firing.
    private func enqueueCommandWork(
        _ commands: [EdgeCommand],
        label: String
    ) {
        commandBusy = true
        commandWorkTask = Task { [weak self] in
            guard let self else { return }
            defer {
                Task { @MainActor [weak self] in
                    self?.commandBusy = false
                    self?.commandWorkTask = nil
                }
            }
            let results = await self.commandHandler.handle(commands)
            for (idx, r) in results.enumerated() {
                let status = r.skipped ? "skipped" : (r.ok ? "ok" : "error")
                let hint: String = {
                    guard let msg = r.message?.trimmingCharacters(in: .whitespacesAndNewlines),
                          !msg.isEmpty
                    else { return "" }
                    let first = msg.split(separator: "\n", omittingEmptySubsequences: false)
                        .map { $0.trimmingCharacters(in: .whitespaces) }
                        .first { !$0.isEmpty } ?? msg
                    let clipped = first.count > 80 ? String(first.prefix(80)) + "…" : String(first)
                    return " · \(clipped)"
                }()
                await MainActor.run {
                    self.postStatus(
                        "Task[\(idx + 1)/\(results.count)] \(status) taskId=\(r.taskId)\(hint)"
                    )
                }
            }
            await MainActor.run {
                self.postStatus(
                    "CommandHandler done \(label): ok=\(results.filter(\.ok).count) " +
                        "skipped=\(results.filter(\.skipped).count) total=\(results.count)"
                )
            }
        }
    }

    /// Expose handler for UI / CommandController wiring.
    var sharedCommandHandler: CommandHandler { commandHandler }

    private func postStatus(_ message: String) {
        listener?.onStatus(message)
    }
}
