import Foundation

/// Pull intents assigned to this iPhone and run preinstalled camera / light / climate / document.scan.
actor RuntimeLoop {
    static let shared = RuntimeLoop()

    private var task: Task<Void, Never>?
    private var inFlight = Set<String>()
    /// Local guard: never re-run capture when Brain step POST failed (158 loop).
    private var finishedKeys = Set<String>()

    func start() {
        task?.cancel()
        task = Task { [weak self] in
            while !Task.isCancelled {
                await self?.tick()
                // Runtime on: pull assigned steps every 2s (POST /intent also triggers pullNow).
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    /// Pull assigned intents immediately (e.g. right after POST /intent).
    func pullNow() async {
        await tick()
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func tick() async {
        guard ParticipantStore.lastReportedRoles.contains("runtime") else { return }
        let pid = ParticipantStore.participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        let url = await AppModel.shared.intentServerURL
        guard !pid.isEmpty, !url.isEmpty else { return }
        let client = await AppModel.shared.intentClient
        let jobs = await client.pullRuntimeIntents(
            edgeId: pid,
            intentURL: url
        )
        for job in jobs {
            let key = job.intentId + "/\(job.step)"
            if inFlight.contains(key) || finishedKeys.contains(key) { continue }
            NSLog(
                "[RuntimeLoop] pull job intent=%@ step=%d cap=%@",
                job.intentId,
                job.step,
                job.capability
            )
            inFlight.insert(key)
            Task {
                await self.execute(job, serverURL: url, edgeId: pid)
                await self.done(key)
            }
        }
        await self.finalizeReadyIntents(client: client, edgeId: pid, intentURL: url)
    }

    private func done(_ key: String) {
        inFlight.remove(key)
    }

    private func postCaptureActionProgress(
        intentId: String,
        step: Int,
        edgeId: String,
        serverURL: String,
        name: String,
        ms: Int,
        started: Bool = false
    ) async {
        let client = await AppModel.shared.intentClient
        let msg: String
        if started, name.hasPrefix("upload") {
            msg = "正在上传（\(name)）"
        } else {
            msg = "action \(name) \(ms)ms"
        }
        _ = await client.postStepStatus(
            intentId: intentId,
            step: step,
            status: 1,
            edgeId: edgeId,
            outputs: nil,
            msg: msg,
            intentURL: serverURL
        )
        if started, name.hasPrefix("upload") {
            _ = await client.postIntentStatus(
                intentId: intentId,
                status: "running",
                edgeId: edgeId,
                message: msg,
                intentURL: serverURL
            )
        }
    }

    private func execute(_ job: RuntimeStepJob, serverURL: String, edgeId: String) async {
        var job = job
        let cap = job.capability
        let client = await AppModel.shared.intentClient
        if IntentClient.hasUnresolvedVars(job.params) {
            if let snap = await client.fetchIntentDetail(
                intentId: job.intentId,
                intentURL: serverURL
            ) {
                job.params = IntentClient.hydrateParams(
                    job.params,
                    snapshot: snap,
                    step: job.step
                )
            }
        }
        if IntentClient.hasUnresolvedVars(job.params) {
            NSLog(
                "[RuntimeLoop] skip %@ intent=%@ step=%d until $vars resolve",
                cap,
                job.intentId,
                job.step
            )
            return
        }
        _ = await client.postStepStatus(
            intentId: job.intentId,
            step: job.step,
            status: 1,
            edgeId: edgeId,
            outputs: nil,
            msg: "executing \(cap)",
            intentURL: serverURL
        )
        _ = await client.postIntentStatus(
            intentId: job.intentId,
            status: "running",
            edgeId: edgeId,
            message: "executing \(cap)",
            intentURL: serverURL
        )
        do {
            let result: (message: String, outputs: [String: Any])
            switch cap {
            case "camera.capture":
                let probe = await GoProDriver().probeAvailable(timeoutSeconds: 2.0)
                if !probe.ok {
                    throw NSError(
                        domain: "CapabilityAvailability",
                        code: 1,
                        userInfo: [NSLocalizedDescriptionKey: probe.message]
                    )
                }
                let intentId = job.intentId
                let step = job.step
                let captureResult = try await GoProCapture.run(
                    intentId: intentId,
                    params: job.params,
                    intentURL: serverURL,
                    onActionBegin: { name in
                        await RuntimeLoop.shared.postCaptureActionProgress(
                            intentId: intentId,
                            step: step,
                            edgeId: edgeId,
                            serverURL: serverURL,
                            name: name,
                            ms: 0,
                            started: true
                        )
                    },
                    onActionComplete: { name, ms in
                        await RuntimeLoop.shared.postCaptureActionProgress(
                            intentId: intentId,
                            step: step,
                            edgeId: edgeId,
                            serverURL: serverURL,
                            name: name,
                            ms: ms
                        )
                    }
                )
                result = (captureResult.message, captureResult.outputs)
            case "asset.upload":
                NSLog(
                    "[RuntimeLoop] asset.upload intent=%@ step=%d params=%@",
                    job.intentId,
                    job.step,
                    String(describing: job.params)
                )
                _ = await client.postStepStatus(
                    intentId: job.intentId,
                    step: job.step,
                    status: 1,
                    edgeId: edgeId,
                    outputs: nil,
                    msg: "正在上传（asset.upload）",
                    intentURL: serverURL
                )
                _ = await client.postIntentStatus(
                    intentId: job.intentId,
                    status: "running",
                    edgeId: edgeId,
                    message: "正在上传（asset.upload）",
                    intentURL: serverURL
                )
                let uploadResult = try await AssetUpload.run(
                    intentId: job.intentId,
                    params: job.params,
                    intentURL: serverURL
                )
                result = (uploadResult.message, uploadResult.outputs)
            case "light.set":
                NSLog(
                    "[RuntimeLoop] light.set intent=%@ step=%d params=%@",
                    job.intentId,
                    job.step,
                    String(describing: job.params)
                )
                let lightResult = try await LivingRoomLight.run(params: job.params)
                result = (lightResult.message, lightResult.outputs)
            case "climate.set":
                NSLog(
                    "[RuntimeLoop] climate.set intent=%@ step=%d params=%@",
                    job.intentId,
                    job.step,
                    String(describing: job.params)
                )
                let climateResult = try await HisenseClimate.run(params: job.params)
                result = (climateResult.message, climateResult.outputs)
            case "document.scan", "visual.input":
                NSLog(
                    "[RuntimeLoop] %@ intent=%@ step=%d params=%@",
                    cap,
                    job.intentId,
                    job.step,
                    String(describing: job.params)
                )
                guard VisualInput.isSupported else {
                    throw VisualInput.InputError.message("扫描失败：本机不支持系统文档扫描。")
                }
                let intentId = job.intentId
                let scanResult = try await VisualInput.runAsCapability(
                    intentId: intentId,
                    params: job.params,
                    intentURL: serverURL,
                    onPhase: { phase in
                        if phase == "waiting" {
                            _ = await client.postIntentStatus(
                                intentId: intentId,
                                status: "waiting",
                                edgeId: edgeId,
                                message: "document.scan: waiting for user",
                                intentURL: serverURL
                            )
                        } else if phase == "uploading" {
                            _ = await client.postIntentStatus(
                                intentId: intentId,
                                status: "running",
                                edgeId: edgeId,
                                message: "document.scan: uploading",
                                intentURL: serverURL
                            )
                        }
                    }
                )
                result = (scanResult.message, scanResult.outputs)
            case "video.live_stream":
                throw NSError(
                    domain: "RuntimeLoop",
                    code: 1,
                    userInfo: [
                        NSLocalizedDescriptionKey:
                            "video.live_stream 是实时视频输入（kind=input），由互动「直播」页或 Larix 自管理推流；不由计划逐步执行",
                    ]
                )
            default:
                result = try await Self.runCapability(job, serverURL: serverURL)
            }
            var posted = false
            for _ in 0 ..< 8 {
                posted = await client.postStepStatus(
                    intentId: job.intentId,
                    step: job.step,
                    status: 2,
                    edgeId: edgeId,
                    outputs: result.outputs,
                    msg: result.message,
                    intentURL: serverURL
                )
                if posted { break }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
            if posted {
                finishedKeys.insert(job.intentId + "/\(job.step)")
            } else {
                NSLog("[RuntimeLoop] step_status=2 not accepted intent=%@ step=%d — stop re-capture", job.intentId, job.step)
                finishedKeys.insert(job.intentId + "/\(job.step)")
            }
            for _ in 0 ..< 5 {
                await finalizeIntentIfComplete(
                    client: client,
                    intentId: job.intentId,
                    edgeId: edgeId,
                    intentURL: serverURL
                )
                if await intentAlreadyTerminal(client: client, intentId: job.intentId, intentURL: serverURL) {
                    break
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        } catch let scanErr as VisualInput.InputError where scanErr.isCancelled {
            let msg = scanErr.localizedDescription
            let outputs: [String: Any] = ["status": "cancelled"]
            _ = await client.postStepStatus(
                intentId: job.intentId,
                step: job.step,
                status: 3,
                edgeId: edgeId,
                outputs: outputs,
                msg: msg,
                intentURL: serverURL
            )
            finishedKeys.insert(job.intentId + "/\(job.step)")
            await finalizeIntentIfComplete(
                client: client,
                intentId: job.intentId,
                edgeId: edgeId,
                intentURL: serverURL
            )
        } catch {
            let msg = error.localizedDescription
            _ = await client.postStepStatus(
                intentId: job.intentId,
                step: job.step,
                status: 3,
                edgeId: edgeId,
                outputs: nil,
                msg: msg,
                intentURL: serverURL
            )
            finishedKeys.insert(job.intentId + "/\(job.step)")
            await finalizeIntentIfComplete(
                client: client,
                intentId: job.intentId,
                edgeId: edgeId,
                intentURL: serverURL
            )
        }
    }

    private static func runCapability(
        _ job: RuntimeStepJob,
        serverURL: String
    ) async throws -> (message: String, outputs: [String: Any]) {
        throw NSError(
            domain: "RuntimeLoop",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "unsupported capability: \(job.capability)"]
        )
    }
}

struct RuntimeStepJob {
    let intentId: String
    let step: Int
    let capability: String
    var params: [String: Any]
}

/// Post intent terminal status when every plan step is done (aligned with Mac executor).
private func finalizeIntentIfComplete(
    client: IntentClient,
    intentId: String,
    edgeId: String,
    intentURL: String
) async {
    guard let snap = await client.fetchIntentDetail(intentId: intentId, intentURL: intentURL) else {
        return
    }
    guard !snap.wireStatus.isTerminal else { return }
    let steps = snap.planSteps
    guard !steps.isEmpty, steps.allSatisfy({ $0.runStatus.isTerminal }) else { return }
    let anyFailed = steps.contains { $0.runStatus == .failed }
    _ = await client.postIntentStatus(
        intentId: intentId,
        status: anyFailed ? "failed" : "succeeded",
        edgeId: edgeId,
        message: anyFailed ? "step failed" : "all steps complete",
        intentURL: intentURL
    )
}

private func intentAlreadyTerminal(client: IntentClient, intentId: String, intentURL: String) async -> Bool {
    guard let snap = await client.fetchIntentDetail(intentId: intentId, intentURL: intentURL) else {
        return false
    }
    return snap.wireStatus.isTerminal
}

extension RuntimeLoop {
    fileprivate func finalizeReadyIntents(client: IntentClient, edgeId: String, intentURL: String) async {
        let rows = await client.peekLivingRoomIntents(edgeId: edgeId, intentURL: intentURL)
        for item in rows {
            let iid = {
                if let s = item["intent_id"] as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
                if let s = item["id"] as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
                if let n = item["intent_id"] as? NSNumber { return n.stringValue }
                if let n = item["id"] as? NSNumber { return n.stringValue }
                if let i = item["intent_id"] as? Int { return String(i) }
                if let i = item["id"] as? Int { return String(i) }
                return ""
            }()
            guard !iid.isEmpty else { continue }
            let wire = (item["status"] as? String ?? item["intent_status"] as? String ?? "")
                .lowercased()
            if wire == "succeeded" || wire == "failed" { continue }
            let plan = item["execution_plan"] as? [[String: Any]] ?? []
            guard !plan.isEmpty else { continue }
            var failed = false
            var allDone = true
            for step in plan {
                let st: Int = {
                    if let i = step["status"] as? Int { return i }
                    if let n = step["status"] as? NSNumber { return n.intValue }
                    if let s = step["status"] as? String { return Int(s) ?? 0 }
                    return 0
                }()
                if st != 2 && st != 3 {
                    allDone = false
                    break
                }
                if st == 3 { failed = true }
            }
            guard allDone else { continue }
            _ = await client.postIntentStatus(
                intentId: iid,
                status: failed ? "failed" : "succeeded",
                edgeId: edgeId,
                message: failed ? "step failed" : "all steps complete",
                intentURL: intentURL
            )
        }
    }
}
