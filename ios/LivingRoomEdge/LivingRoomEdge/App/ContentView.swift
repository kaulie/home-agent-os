import SwiftUI
import UIKit

enum ScheduleInterval: Int, CaseIterable, Identifiable {
    case oneMinute = 60
    case twoMinutes = 120
    case fiveMinutes = 300
    case fifteenMinutes = 900

    var id: Int { rawValue }

    var label: String {
        "\(rawValue / 60)分钟"
    }
}

private enum GoProPanelKind {
    case status
    case capture
    case latest

    var actionName: String {
        switch self {
        case .status: return "status"
        case .capture: return "capture_photo"
        case .latest: return "latest_photo"
        }
    }

    var title: String {
        switch self {
        case .status: return "状态查询"
        case .capture: return "拍照"
        case .latest: return "下载最新照片"
        }
    }

    var urlLabel: String {
        switch self {
        case .status: return "Status URL（插件内固定）"
        case .capture: return "Shutter URL（插件内固定）"
        case .latest: return "Media list URL（插件内固定）"
        }
    }

    /// Display-only; camera endpoints live in the GoPro plugin (not Edge-owned).
    var displayURL: String {
        switch self {
        case .status: return "http://10.5.5.9/gp/gpControl/status"
        case .capture: return "http://10.5.5.9/gp/gpControl/command/shutter?p=1"
        case .latest: return "http://10.5.5.9/gp/gpMediaList"
        }
    }

    var runButtonTitle: String {
        switch self {
        case .status: return "查询状态"
        case .capture: return "拍照"
        case .latest: return "下载最新照片"
        }
    }

    var supportsSchedule: Bool {
        switch self {
        case .status, .capture: return true
        case .latest: return false
        }
    }

    var scheduleOnTitle: String {
        switch self {
        case .status: return "开启轮询"
        case .capture: return "开启定期拍照"
        case .latest: return ""
        }
    }

    var scheduleOffTitle: String {
        switch self {
        case .status: return "关闭轮询"
        case .capture: return "关闭定期拍照"
        case .latest: return ""
        }
    }

    var eventsTitle: String {
        switch self {
        case .status: return "状态查询事件"
        case .capture: return "拍照事件"
        case .latest: return "下载照片事件"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var logs = LogStore()
    @StateObject private var tickLogs = AgentTickLogStore()
    @StateObject private var speech = SpeechRecognizer()
    @StateObject private var clicks = ClickGuard()
    @State private var agentStatus = "Agent：未启动"
    @State private var agentPollLogHeight: CGFloat = 140
    @State private var agentPollLogDragStart: CGFloat = 140

    @State private var statusCopyHint = ""
    @State private var captureCopyHint = ""
    @State private var latestCopyHint = ""

    @State private var statusInterval: ScheduleInterval = .oneMinute
    @State private var statusPolling = false
    @State private var statusPollTask: Task<Void, Never>?

    @State private var captureInterval: ScheduleInterval = .oneMinute
    @State private var captureScheduling = false
    @State private var captureScheduleTask: Task<Void, Never>?

    @State private var goproSectionExpanded = true
    @State private var chromecastSectionExpanded = true
    @State private var castPhotoURL = AppModel.defaultCastPhotoURL
    @State private var castBusy = false
    @State private var castHint = ""
    @State private var castResultText = ""
    @State private var showLatestPhotoPreview = false
    @State private var previewError = ""
    @State private var showRedownloadConfirm = false
    @State private var redownloadPrompt: RedownloadPrompt?
    @State private var latestDownloadBusy = false
    @State private var statusBusy = false
    @State private var captureBusy = false
    @State private var uploadCopyHint = ""
    @State private var uploadBusy = false
    @State private var serverDownloadCopyHint = ""
    @State private var serverDownloadBusy = false
    @State private var showServerDownloadPreview = false
    @State private var saveAlbumHint = ""
    @State private var saveAlbumBusy = false

    @State private var intentServerURL = AppModel.defaultIntentURL
    @State private var intentText = ""
    @State private var intentSource: String = "text"
    @State private var intentBusy = false
    @State private var intentCopyHint = ""
    @State private var intentHint = ""

    @State private var edgeRegisterURL = AppModel.defaultEdgeRegisterURL
    @State private var edgeHeartbeatURL = AppModel.defaultEdgeHeartbeatURL
    @State private var edgeRegisterBusy = false
    @State private var edgeHeartbeatBusy = false
    @State private var edgeRegisterHint = ""
    @State private var edgeRegisterCopyHint = ""
    @State private var edgeHeartbeatCopyHint = ""

    private struct RedownloadPrompt: Identifiable {
        let id = UUID()
        let name: String
        let timestamp: String
        let localPath: String
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    header
                    agentControls
                    edgeInfoPanel
                    edgeNodeRegisterPanel
                    intentDispatchPanel

                    goproSection

                    chromecastCastSection

                    logPanel
                }
                .padding()
            }
            .navigationTitle("客厅 Edge · iPhone")
            .onAppear { wireAgentListener() }
            .onDisappear {
                stopStatusPolling(log: false)
                stopCaptureSchedule(log: false)
            }
            .sheet(isPresented: $showLatestPhotoPreview) {
                LatestPhotoPreviewSheet(
                    path: model.latestPhotoPath,
                    onClose: { showLatestPhotoPreview = false },
                    onSave: {
                        guard clicks.tryTap() else { return }
                        saveToAlbum(path: model.latestPhotoPath)
                    }
                )
            }
            .sheet(isPresented: $showServerDownloadPreview) {
                LatestPhotoPreviewSheet(
                    path: model.serverPhotoPath,
                    onClose: { showServerDownloadPreview = false },
                    onSave: {
                        guard clicks.tryTap() else { return }
                        saveToAlbum(path: model.serverPhotoPath)
                    }
                )
            }
            .onChange(of: model.latestPhotoPath) { _ in
                if model.latestPhotoPath != nil {
                    previewError = ""
                }
            }
            .confirmationDialog(
                "照片已下载过",
                isPresented: $showRedownloadConfirm,
                titleVisibility: .visible
            ) {
                Button("重新下载") {
                    guard clicks.tryTap() else { return }
                    redownloadPrompt = nil
                    beginLatestDownload(force: true)
                }
                Button("使用已有文件", role: .cancel) {
                    guard clicks.tryTap(cooldown: 0.4) else { return }
                    if let prompt = redownloadPrompt {
                        model.latestPhotoPath = prompt.localPath
                        model.latestApiResponse =
                            "已存在 \(prompt.name) ts=\(prompt.timestamp) · \(prompt.localPath)"
                        model.latestEvents.insert(
                            GoProActionEvent(ok: true, body: model.latestApiResponse),
                            at: 0
                        )
                        logs.append("使用已下载照片：\(prompt.name)")
                    }
                    redownloadPrompt = nil
                }
            } message: {
                if let prompt = redownloadPrompt {
                    Text("\(prompt.name)（时间戳 \(prompt.timestamp)）本地已存在，是否重新下载？")
                } else {
                    Text("本地已存在该照片，是否重新下载？")
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(AppModel.edgeIdentity.displayName)
                .font(.headline)
            Text(
                "edgeId=\(model.edgeId)"
                    + (model.edgeAgent.assignedEdgeId == nil ? "（未注册）" : "（已签发）")
                    + " · hint=\(AppModel.preferredEdgeId)"
                    + " · device=\(AppModel.edgeIdentity.deviceType.rawValue)"
            )
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(agentStatus)
                .font(.subheadline)
                .foregroundStyle(.blue)
            if let info = model.lastEdgeInfo {
                let capCount = info.services.reduce(0) { $0 + $1.capabilities.count }
                Text(
                    "上报：\(info.onlineStatus.rawValue) · health=\(info.health.status.rawValue) · services=\(info.services.count) · caps=\(capCount)"
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
    }

    private var agentControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button("启动 Agent") {
                    guard clicks.tryTap() else { return }
                    model.edgeAgent.start()
                    agentStatus = "Agent：运行中"
                    logs.append("用户：启动 Agent")
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.edgeAgent.running)

                Button("停止 Agent") {
                    guard clicks.tryTap() else { return }
                    stopStatusPolling(log: true)
                    stopCaptureSchedule(log: true)
                    model.edgeAgent.stop()
                    agentStatus = "Agent：已停止"
                    logs.append("用户：停止 Agent")
                }
                .buttonStyle(.bordered)
                .disabled(!model.edgeAgent.running)
            }

            agentTickLogsPanel
        }
    }

    /// Heartbeat + intents pull logs side by side; height drag handle at bottom.
    private var agentTickLogsPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Agent 轮询（心跳 · 意图拉取，各保留最近 5 次）")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            HStack(alignment: .top, spacing: 8) {
                tickLogBox(title: "Heartbeat", lines: tickLogs.heartbeatLines)
                tickLogBox(title: "Intents 拉取", lines: tickLogs.intentLines)
            }

            // Drag to resize both boxes.
            HStack {
                Spacer()
                Capsule()
                    .fill(Color.secondary.opacity(0.45))
                    .frame(width: 44, height: 5)
                Spacer()
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 4)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 2)
                    .onChanged { value in
                        let next = agentPollLogDragStart + value.translation.height
                        agentPollLogHeight = min(280, max(72, next))
                    }
                    .onEnded { _ in
                        agentPollLogDragStart = agentPollLogHeight
                    }
            )
            .accessibilityLabel("拖动调整轮询日志高度")
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func tickLogBox(title: String, lines: [String]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.weight(.semibold))
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    if lines.isEmpty {
                        Text("（尚无轮询）")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                            Text(line)
                                .font(.system(.caption2, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
            .frame(height: agentPollLogHeight)
            .padding(6)
            .background(Color(.tertiarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var edgeInfoPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Edge 信息上报")
                .font(.title3.weight(.semibold))
            Text("两条独立机制：① Capability 插件在 Edge 本地注册；② 先 POST /edge-register 拿 edgeId，再心跳 /edge-heartbeat")
                .font(.caption)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                Text("① Edge 本地 Service 插件")
                    .font(.subheadline.weight(.semibold))
                if model.capabilityRegistry.all().isEmpty {
                    Text("（无）")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(model.capabilityRegistry.services()) { svc in
                        Text(
                            "· \(svc.serviceId) [\(svc.group)] v\(svc.version) · caps [\(svc.capabilities.map(\.capabilityId).joined(separator: ", "))]"
                        )
                        .font(.system(.caption2, design: .monospaced))
                    }
                }
            }

            if let info = model.lastEdgeInfo {
                VStack(alignment: .leading, spacing: 4) {
                    Text("② 最近一次上报给 Brain")
                        .font(.subheadline.weight(.semibold))
                    Text("身份：\(info.displayName)（edgeId=\(info.edgeId)）")
                    if model.edgeAgent.assignedEdgeId == nil {
                        Text("提示：尚未拿到 Brain 签发的 edgeId（启动 Agent 会先走 /edge-register）")
                            .foregroundStyle(.orange)
                    }
                    Text("设备：\(info.deviceType.rawValue) · 房间：\(info.room)")
                    Text("状态：\(info.onlineStatus.rawValue) · 健康：\(info.health.status.rawValue) — \(info.health.summary)")
                    Text(
                        "上报 Services：\(info.services.map { "\($0.serviceId)(\($0.group))" }.joined(separator: ", "))"
                    )
                    let caps = info.services.flatMap { $0.capabilities.map(\.capabilityId) }
                    Text("上报 Capabilities：\(caps.joined(separator: ", "))")
                }
                .font(.system(.caption2, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
            } else {
                Text("② 尚未向 Brain 上报（请先启动 Agent）")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var edgeNodeRegisterPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Edge 节点注册")
                .font(.title3.weight(.semibold))
            Text("首次无本地 edge_id 才调用 /edge-register；成功后写入本地文件，以后启动与注册都复用，不再重复注册。心跳用已缓存的 edge_id。")
                .font(.caption)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text("Register URL")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                TextField(AppModel.defaultEdgeRegisterURL, text: $edgeRegisterURL)
                    .textFieldStyle(.roundedBorder)
                    .font(.caption)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
                    .textInputAutocapitalization(.never)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("Heartbeat URL")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                TextField(AppModel.defaultEdgeHeartbeatURL, text: $edgeHeartbeatURL)
                    .textFieldStyle(.roundedBorder)
                    .font(.caption)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
                    .textInputAutocapitalization(.never)
            }

            Text("注册 / 心跳只上报设备插件（GoPro）；intent.dispatch / commands.pull 仅本地调试，不注册到 Brain。")
                .font(.caption2)
                .foregroundStyle(.secondary)

            HStack(spacing: 8) {
                Button(edgeRegisterBusy ? "注册中…" : "注册") {
                    guard clicks.tryTap() else { return }
                    beginEdgeNodeRegister()
                }
                .buttonStyle(.borderedProminent)
                .disabled(edgeRegisterBusy || edgeHeartbeatBusy)

                Button(edgeHeartbeatBusy ? "心跳中…" : "心跳") {
                    guard clicks.tryTap() else { return }
                    beginEdgeHeartbeat()
                }
                .buttonStyle(.bordered)
                .disabled(edgeRegisterBusy || edgeHeartbeatBusy)

                Button("清除本地 edgeId") {
                    guard clicks.tryTap(cooldown: 0.4) else { return }
                    model.edgeAgent.clearAssignedEdgeId()
                    edgeRegisterHint = "已清除本地 edgeId，请重新注册"
                    logs.append("用户：清除本地 edgeId")
                }
                .buttonStyle(.bordered)
                .disabled(edgeRegisterBusy || edgeHeartbeatBusy)

                Button("清空返回") {
                    guard clicks.tryTap(cooldown: 0.4) else { return }
                    model.edgeRegisterApiResponse = ""
                    model.edgeHeartbeatApiResponse = ""
                    edgeRegisterHint = ""
                }
                .buttonStyle(.bordered)
                .disabled(edgeRegisterBusy || edgeHeartbeatBusy)
            }

            if !edgeRegisterHint.isEmpty {
                Text(edgeRegisterHint)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }

            Text("当前 edgeId：\(model.edgeId)" + (model.edgeAgent.assignedEdgeId == nil ? "（未签发）" : "（已签发）"))
                .font(.caption2)
                .foregroundStyle(.secondary)

            responseBox(
                title: "注册返回",
                text: model.edgeRegisterApiResponse,
                copyHint: $edgeRegisterCopyHint
            )
            responseBox(
                title: "心跳返回",
                text: model.edgeHeartbeatApiResponse,
                copyHint: $edgeHeartbeatCopyHint
            )
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func responseBox(title: String, text: String, copyHint: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Spacer()
                if !copyHint.wrappedValue.isEmpty {
                    Text(copyHint.wrappedValue)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Button("复制") {
                    UIPasteboard.general.string = text
                    copyHint.wrappedValue = "已复制"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        copyHint.wrappedValue = ""
                    }
                }
                .buttonStyle(.bordered)
                .disabled(text.isEmpty)
            }

            Text(text.isEmpty ? "（暂无）" : text)
                .font(.system(.caption, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding(8)
                .frame(minHeight: 80, alignment: .topLeading)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    private func beginEdgeNodeRegister() {
        guard !edgeRegisterBusy, !edgeHeartbeatBusy else { return }
        let server = edgeRegisterURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            edgeRegisterHint = "请填写 Register URL"
            return
        }

        // 已有本地缓存的 edge_id → 不重复注册
        if let cached = model.edgeAgent.assignedEdgeId?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !cached.isEmpty {
            edgeRegisterHint = "已注册，复用本地 edge_id=\(cached)（如需换号请先「清除本地 edgeId」）"
            model.edgeRegisterApiResponse =
                "{\"ok\":true,\"status\":\"cached\",\"edge_id\":\"\(cached)\",\"message\":\"skip register; reuse local file\"}"
            logs.append("跳过注册，复用缓存 edge_id=\(cached)")
            return
        }

        // Same filter as Agent heartbeat/register (Cast temporarily not advertised).
        let services = model.edgeAgent.servicesForBrain()

        edgeRegisterBusy = true
        edgeRegisterHint = ""
        logs.append("本地无 edge_id，开始注册 → \(server)")

        Task { @MainActor in
            let request = EdgeRegisterRequest(
                clientHint: AppModel.preferredEdgeId,
                displayName: AppModel.edgeIdentity.displayName,
                deviceType: AppModel.edgeIdentity.deviceType,
                room: AppModel.edgeIdentity.room,
                services: services,
                appVersion: AppModel.edgeIdentity.appVersion
            )
            do {
                let (response, raw, _) = try await model.edgeReporter.register(
                    request,
                    urlOverride: server
                )
                model.edgeRegisterApiResponse = raw
                if response.isApproved {
                    model.edgeAgent.adoptAssignedEdgeId(response.edgeId)
                    edgeRegisterHint =
                        "注册成功，已写入本地文件 edge_id=\(response.edgeId)"
                    logs.append("Edge 注册成功并落盘 edge_id=\(response.edgeId)")
                } else {
                    edgeRegisterHint = "注册未通过：\(response.debugSummary)"
                    logs.append("Edge 注册未通过：\(response.debugSummary)")
                }
            } catch {
                model.edgeRegisterApiResponse = error.localizedDescription
                edgeRegisterHint = "注册失败：\(error.localizedDescription)"
                logs.append("Edge 注册失败：\(error.localizedDescription.prefix(160))")
            }
            edgeRegisterBusy = false
        }
    }

    private func beginEdgeHeartbeat() {
        guard !edgeRegisterBusy, !edgeHeartbeatBusy else { return }
        let server = edgeHeartbeatURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            edgeRegisterHint = "请填写 Heartbeat URL"
            return
        }
        guard model.edgeAgent.assignedEdgeId != nil else {
            edgeRegisterHint = "请先注册拿到 edgeId，再发心跳"
            return
        }

        edgeHeartbeatBusy = true
        edgeRegisterHint = ""
        logs.append("Edge 心跳 → \(server)")

        Task { @MainActor in
            let info = model.edgeAgent.buildNodeInfo(online: .online)
            do {
                let raw = try await model.edgeReporter.heartbeat(info, urlOverride: server)
                model.edgeHeartbeatApiResponse = raw
                model.lastEdgeInfo = info
                edgeRegisterHint = "心跳成功 edgeId=\(info.edgeId)"
                logs.append("Edge 心跳成功")
            } catch {
                model.edgeHeartbeatApiResponse = error.localizedDescription
                edgeRegisterHint = "心跳失败"
                logs.append("Edge 心跳失败：\(error.localizedDescription.prefix(120))")
                let ns = error as NSError
                if ns.domain == "HttpEdgeReporter", ns.code == 401 {
                    model.edgeAgent.clearAssignedEdgeId()
                    edgeRegisterHint = "edgeId 未被 Brain 认可，已清除，请重新注册"
                }
            }
            edgeHeartbeatBusy = false
        }
    }

    private var intentDispatchPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("用户意图")
                .font(.title3.weight(.semibold))
            Text("文本直接发送；语音先在本机转成文字，再 POST 到服务器")
                .font(.caption)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text("Intent URL")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                TextField("http://115.190.153.53:9527/api/v1/intent", text: $intentServerURL)
                    .textFieldStyle(.roundedBorder)
                    .font(.caption)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
                    .textInputAutocapitalization(.never)
            }

            TextField("输入指令，例如：帮我拍张照", text: $intentText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(3 ... 6)
                .onChange(of: intentText) { newValue in
                    // Manual edit after voice → still allow send; mark text if diverged from transcript
                    if !speech.isRecording,
                       newValue != speech.transcript,
                       intentSource == "voice",
                       !speech.transcript.isEmpty,
                       !newValue.hasPrefix(speech.transcript) {
                        intentSource = "text"
                    }
                }
                .onChange(of: speech.transcript) { newValue in
                    if speech.isRecording || !newValue.isEmpty {
                        intentText = newValue
                        if speech.isRecording {
                            intentSource = "voice"
                        }
                    }
                }

            HStack(spacing: 8) {
                Button(speech.isRecording ? "停止录音" : "开始录音") {
                    guard clicks.tryTap(cooldown: 0.5) else { return }
                    Task {
                        if speech.isRecording {
                            speech.stop()
                            intentSource = "voice"
                            if !speech.transcript.isEmpty {
                                intentText = speech.transcript
                            }
                            intentHint = speech.transcript.isEmpty ? "未识别到内容" : "已转写，可发出"
                        } else {
                            speech.clearTranscript()
                            intentSource = "voice"
                            intentHint = "正在聆听…"
                            await speech.start()
                        }
                    }
                }
                .buttonStyle(.bordered)
                .tint(speech.isRecording ? .red : .accentColor)
                .disabled(intentBusy)

                Button(intentBusy ? "发出中…" : "发出指令") {
                    guard clicks.tryTap() else { return }
                    beginIntentDispatch()
                }
                .buttonStyle(.borderedProminent)
                .disabled(intentBusy)

                Button("清空") {
                    guard clicks.tryTap(cooldown: 0.4) else { return }
                    intentText = ""
                    intentSource = "text"
                    intentHint = ""
                    speech.clearTranscript()
                }
                .buttonStyle(.bordered)
                .disabled(intentBusy || speech.isRecording)
            }

            HStack(spacing: 8) {
                Text("来源：\(intentSource == "voice" ? "语音" : "文本")")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                if !speech.statusMessage.isEmpty {
                    Text(speech.statusMessage)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            if !speech.lastError.isEmpty {
                Text(speech.lastError)
                    .font(.caption2)
                    .foregroundStyle(.red)
            }
            if !intentHint.isEmpty {
                Text(intentHint)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }

            if let journey = model.activeIntentJourney {
                IntentLogisticsTimelineView(journey: journey)
            } else {
                Text("发出指令后将以物流时间线展示执行状态")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            DisclosureGroup("服务器返回（调试）") {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Spacer()
                        if !intentCopyHint.isEmpty {
                            Text(intentCopyHint)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Button("复制") {
                            UIPasteboard.general.string = model.intentApiResponse
                            intentCopyHint = "已复制"
                            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { intentCopyHint = "" }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.intentApiResponse.isEmpty)
                    }

                    Text(model.intentApiResponse.isEmpty ? "（暂无）" : model.intentApiResponse)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(8)
                        .frame(minHeight: 60, alignment: .topLeading)
                        .background(Color(.tertiarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .font(.subheadline.weight(.semibold))

            VStack(alignment: .leading, spacing: 6) {
                Text("指令事件")
                    .font(.subheadline.weight(.semibold))
                ScrollView {
                    if model.intentEvents.isEmpty {
                        Text("（暂无执行记录）")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(model.intentEvents) { event in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(event.timeText)
                                            .foregroundStyle(.secondary)
                                        Text(event.resultText)
                                            .foregroundStyle(event.ok ? .green : .red)
                                            .fontWeight(.semibold)
                                    }
                                    Text(event.body.isEmpty ? "（无返回内容）" : event.body)
                                        .foregroundStyle(.primary)
                                        .textSelection(.enabled)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .font(.system(.caption2, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .frame(height: 140)
                .padding(8)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .onDisappear {
            if speech.isRecording { speech.stop() }
        }
        .onChange(of: model.intentEvents.count) { _ in
            intentBusy = false
        }
        .onChange(of: model.intentApiResponse) { _ in
            // Dispatch finished (success or failure body) — never leave button stuck.
            intentBusy = false
        }
    }

    private func beginIntentDispatch() {
        guard !intentBusy else { return }
        if speech.isRecording {
            speech.stop()
            if !speech.transcript.isEmpty {
                intentText = speech.transcript
                intentSource = "voice"
            }
        }

        let text = intentText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            intentHint = "请先输入文字或完成语音识别"
            return
        }
        let server = intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            intentHint = "请填写 Intent URL"
            return
        }
        guard model.edgeAgent.running else {
            logs.append("提示：先启动 Agent 再发出指令")
            intentHint = "请先启动 Agent"
            return
        }

        // If user typed after voice, treat as text unless last capture was voice and text matches transcript
        let source: String
        if intentSource == "voice", text == speech.transcript.trimmingCharacters(in: .whitespacesAndNewlines) {
            source = "voice"
        } else if intentSource == "voice", !speech.transcript.isEmpty {
            source = "voice"
        } else {
            source = "text"
        }

        intentBusy = true
        intentHint = ""
        // Prefill so Edge job status reports use the same host even before POST returns.
        model.intentController.lastServerURL = server
        // Show timeline immediately (do not wait for server job_id).
        model.intentJourney.startOptimistic(text: text)
        let plan = model.brain.enqueueSkillAction(
            edgeId: model.edgeId,
            skillId: IntentSkill.skillId,
            action: "dispatch",
            params: [
                "text": text,
                "source": source,
                "server_url": server,
            ]
        )
        model.pendingPlans[plan.planId] = (action: "dispatch", updateSnapshot: true)
        logs.append("注入 Plan \(plan.planId): intent.dispatch (\(source))")
        model.edgeAgent.pollNow()
        // Backstop if plan pipeline stalls (should be rare after local-plans-first tick).
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
            if intentBusy {
                intentBusy = false
                if intentHint.isEmpty {
                    intentHint = "发出超时，可重试"
                }
            }
        }
    }

    private var goproSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 8) {
                Text("GoPro Camera (\(GoProPluginEntry.skillId))")
                    .font(.headline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        goproSectionExpanded.toggle()
                    }
                } label: {
                    Image(systemName: goproSectionExpanded ? "chevron.up.circle.fill" : "chevron.down.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel(goproSectionExpanded ? "折叠 GoPro 区域" : "展开 GoPro 区域")
                }
                .buttonStyle(.plain)
            }

            if goproSectionExpanded {
                Text("GoPro当前状态：\(model.goproCurrentStatus)\(model.goproStatusTimeSuffix)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                panel(.status)
                panel(.capture)
                panel(.latest)
                uploadPanel
                serverDownloadPanel
            }
        }
    }

    private var chromecastCastSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 8) {
                Text("Chromecast 投屏 (\(ChromecastCastSkill.skillId))")
                    .font(.headline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        chromecastSectionExpanded.toggle()
                    }
                } label: {
                    Image(systemName: chromecastSectionExpanded ? "chevron.up.circle.fill" : "chevron.down.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel(chromecastSectionExpanded ? "折叠 Chromecast 区域" : "展开 Chromecast 区域")
                }
                .buttonStyle(.plain)
            }

            if chromecastSectionExpanded {
                Text(
                    """
                    自定义 Receiver 的 HTML 由 Cast Console 登记的 Receiver URL 加载，不是 iPhone 里填的 http://192.168.3.8:8080/；手机端只需拉起 App ID \(CastSessionController.receiverAppID)。若 Console 里 Receiver URL 指向局域网 HTML，需确保 Chromecast 能访问该 URL（Cast 常要求 HTTPS，局域网 http 可能被拦）。
                    """
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

                Button(castBusy ? "启动中…" : "启动自定义 Receiver") {
                    guard clicks.tryTap() else { return }
                    beginLaunchCustomReceiver()
                }
                .buttonStyle(.borderedProminent)
                .disabled(castBusy)

                Text(
                    """
                    本地网络：系统弹窗通常只出现一次。Bonjour 有设备但 Cast SDK 为空时，到「设置 → 隐私与安全性 → 本地网络」打开本 App；无条目则删 App 重装后再点「请求本地网络权限」。
                    """
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    Button("请求本地网络权限") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        CastSessionController.shared.requestLocalNetworkPermission()
                        castHint = "已触发 Bonjour + Cast 发现；若权限未决应弹出系统对话框…"
                        logs.append("Cast: request local network permission")
                        Task { @MainActor in
                            let status = await CastSessionController.shared.refreshDiscovery(waitSeconds: 14)
                            castHint = status
                            logs.append("Cast discovery after LN request: \(status)")
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(castBusy)

                    Button("刷新发现") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        castHint = "正在刷新 Cast 发现…"
                        Task { @MainActor in
                            let status = await CastSessionController.shared.refreshDiscovery(waitSeconds: 14)
                            castHint = status
                            logs.append("Cast discovery: \(status)")
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(castBusy)

                    Button("断开 Cast") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        CastSessionController.shared.disconnect()
                        castHint = "已请求断开 Cast session"
                        logs.append("Cast: disconnect")
                    }
                    .buttonStyle(.bordered)
                    .disabled(castBusy)
                }

                Divider().padding(.vertical, 4)

                Text("图片投屏（自定义 Receiver \(CastSessionController.receiverAppID) + \(CastSessionController.imageMessageNamespace)）")
                    .font(.subheadline.weight(.semibold))
                Text("连接 F7649303 后发送 {\"url\":\"…\"}，不走 loadMedia，也不回退 Default Media Receiver。photo_url 须为 http(s) 图片地址（/img/…、/xxx.JPG 或 /latest）。")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(alignment: .leading, spacing: 4) {
                    Text("photo_url")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    TextField("http://115.190.153.53:8080/….JPG 或云上 saved_as", text: $castPhotoURL)
                        .textFieldStyle(.roundedBorder)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .disabled(castBusy)
                }

                HStack(spacing: 8) {
                    Button(castBusy ? "投屏中…" : "投屏图片到 Chromecast") {
                        guard clicks.tryTap() else { return }
                        beginChromecastCast()
                    }
                    .buttonStyle(.bordered)
                    .disabled(castBusy || castPhotoURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    Button("恢复默认 URL") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        castPhotoURL = AppModel.defaultCastPhotoURL
                        castHint = ""
                    }
                    .buttonStyle(.bordered)
                    .disabled(castBusy)
                }

                if !castHint.isEmpty {
                    Text(castHint)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }

                if !castResultText.isEmpty {
                    Text(castResultText)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(8)
                        .background(Color(.tertiarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func beginLaunchCustomReceiver() {
        castBusy = true
        castHint = "正在启动自定义 Receiver \(CastSessionController.receiverAppID)…"
        castResultText = ""
        logs.append("Cast → launchCustomReceiver app=\(CastSessionController.receiverAppID)")
        Task { @MainActor in
            let result = await CastSessionController.shared.launchCustomReceiver { step in
                castHint = step
                logs.append("Cast \(step)")
            }
            castBusy = false
            castResultText = result.message
            castHint = result.ok
                ? "自定义 Receiver 已启动（TV 应显示 Console 登记的 HTML）"
                : "自定义 Receiver 启动失败（见下方错误与 Console 清单）"
            logs.append(
                result.ok
                    ? "Cast custom receiver ok · \(result.message)"
                    : "Cast custom receiver failed · \(result.message)"
            )
        }
    }

    private func beginChromecastCast() {
        let url = castPhotoURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else {
            castHint = "请输入 photo_url"
            return
        }
        castBusy = true
        castHint = "图片投屏中…"
        castResultText = ""
        logs.append("Cast photo → \(url)")
        Task { @MainActor in
            let result = await CastSessionController.shared.castPhoto(urlString: url) { step in
                castHint = step
                logs.append("Cast \(step)")
            }
            castBusy = false
            castResultText = result.message
            castHint = result.ok
                ? "图片消息已发送（若 TV 无画面：检查 Receiver 是否监听 urn:x-cast:local.image，以及 Cast 能否访问该 URL）"
                : "图片投屏失败"
            logs.append(result.ok ? "Cast photo ok · \(result.message)" : "Cast photo failed · \(result.message)")
        }
    }

    private var uploadPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("上传照片")
                .font(.title3.weight(.semibold))
            Text("上传最近一次下载的照片（multipart 字段 file）")
                .font(.caption)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text("Server URL（App 展示用，插件自持实际地址）")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(AppModel.defaultUploadURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            if let path = model.goproPlugin.lastPhotoLocalPath
                ?? model.serverPhotoPath
                ?? model.latestPhotoPath {
                Text("将上传：\(path)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text("尚无本地照片，请先从 GoPro 或服务器下载")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }

            HStack(spacing: 8) {
                Button(uploadBusy ? "上传中…" : "上传照片") {
                    guard clicks.tryTap() else { return }
                    beginUpload()
                }
                .buttonStyle(.borderedProminent)
                .disabled(uploadBusy)
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("接口返回")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    if !uploadCopyHint.isEmpty {
                        Text(uploadCopyHint)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Button("复制") {
                        UIPasteboard.general.string = model.uploadApiResponse
                        uploadCopyHint = "已复制"
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { uploadCopyHint = "" }
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.uploadApiResponse.isEmpty)
                }

                Text(model.uploadApiResponse.isEmpty ? "（暂无）" : model.uploadApiResponse)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(8)
                    .frame(minHeight: 80, alignment: .topLeading)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("上传事件")
                    .font(.subheadline.weight(.semibold))
                ScrollView {
                    if model.uploadEvents.isEmpty {
                        Text("（暂无执行记录）")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(model.uploadEvents) { event in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(event.timeText)
                                            .foregroundStyle(.secondary)
                                        Text(event.resultText)
                                            .foregroundStyle(event.ok ? .green : .red)
                                            .fontWeight(.semibold)
                                    }
                                    Text(event.body.isEmpty ? "（无返回内容）" : event.body)
                                        .foregroundStyle(.primary)
                                        .textSelection(.enabled)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .font(.system(.caption2, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .frame(height: 140)
                .padding(8)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .onChange(of: model.uploadEvents.count) { _ in
            uploadBusy = false
        }
        .onChange(of: model.uploadApiResponse) { _ in
            if !model.uploadApiResponse.isEmpty {
                uploadBusy = false
            }
        }
    }

    private var serverDownloadPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("从服务器下载最新照片")
                .font(.title3.weight(.semibold))
            Text("GET download_latest（按服务器目录修改时间取最新一张）")
                .font(.caption)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 2) {
                Text("Server URL（App 展示用，插件自持实际地址）")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(AppModel.defaultServerDownloadURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            HStack(spacing: 8) {
                Button(serverDownloadBusy ? "下载中…" : "从服务器下载") {
                    guard clicks.tryTap() else { return }
                    beginServerDownload()
                }
                .buttonStyle(.borderedProminent)
                .disabled(serverDownloadBusy)

                Button("预览") {
                    guard clicks.tryTap(cooldown: 0.4) else { return }
                    if serverDownloadBusy {
                        previewError = "仍在下载，请稍候"
                    } else if model.serverPhotoPath == nil {
                        previewError = "尚无「服务器下载」的照片，请先完成下载"
                    } else {
                        previewError = ""
                        showServerDownloadPreview = true
                    }
                }
                .buttonStyle(.bordered)
                .disabled(serverDownloadBusy || model.serverPhotoPath == nil)

                Button(saveAlbumBusy ? "保存中…" : "保存到相册") {
                    guard clicks.tryTap() else { return }
                    saveToAlbum(path: model.serverPhotoPath)
                }
                .buttonStyle(.bordered)
                .disabled(serverDownloadBusy || saveAlbumBusy || model.serverPhotoPath == nil)
            }

            if let path = model.serverPhotoPath, !serverDownloadBusy {
                Text("服务器照片：\(path)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else if serverDownloadBusy {
                Text("正在从服务器下载…")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }

            if !saveAlbumHint.isEmpty {
                Text(saveAlbumHint)
                    .font(.caption2)
                    .foregroundStyle(saveAlbumHint.contains("失败") || saveAlbumHint.contains("未授权") ? .red : .green)
            }

            if !previewError.isEmpty {
                Text(previewError)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("接口返回")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    if !serverDownloadCopyHint.isEmpty {
                        Text(serverDownloadCopyHint)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Button("复制") {
                        UIPasteboard.general.string = model.serverDownloadApiResponse
                        serverDownloadCopyHint = "已复制"
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                            serverDownloadCopyHint = ""
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.serverDownloadApiResponse.isEmpty)
                }

                Text(model.serverDownloadApiResponse.isEmpty ? "（暂无）" : model.serverDownloadApiResponse)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(8)
                    .frame(minHeight: 80, alignment: .topLeading)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("服务器下载事件")
                    .font(.subheadline.weight(.semibold))
                ScrollView {
                    if model.serverDownloadEvents.isEmpty {
                        Text("（暂无执行记录）")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(model.serverDownloadEvents) { event in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(event.timeText)
                                            .foregroundStyle(.secondary)
                                        Text(event.resultText)
                                            .foregroundStyle(event.ok ? .green : .red)
                                            .fontWeight(.semibold)
                                    }
                                    Text(event.body.isEmpty ? "（无返回内容）" : event.body)
                                        .foregroundStyle(.primary)
                                        .textSelection(.enabled)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .font(.system(.caption2, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .frame(height: 140)
                .padding(8)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .onChange(of: model.serverDownloadEvents.count) { _ in
            serverDownloadBusy = false
        }
        .onChange(of: model.serverDownloadApiResponse) { _ in
            if !model.serverDownloadApiResponse.isEmpty {
                serverDownloadBusy = false
            }
        }
    }

    private func saveToAlbum(path: String?) {
        guard let path, !path.isEmpty else {
            saveAlbumHint = "没有可保存的照片"
            return
        }
        guard !saveAlbumBusy else { return }
        saveAlbumBusy = true
        saveAlbumHint = ""
        Task { @MainActor in
            defer { saveAlbumBusy = false }
            do {
                try await PhotoAlbumSaver.save(filePath: path)
                saveAlbumHint = "已保存到相册"
                logs.append("已保存到相册：\(path)")
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                    if saveAlbumHint == "已保存到相册" { saveAlbumHint = "" }
                }
            } catch {
                saveAlbumHint = error.localizedDescription
                logs.append("保存相册失败：\(error.localizedDescription)")
            }
        }
    }

    private func beginUpload() {
        guard !uploadBusy else { return }
        guard model.edgeAgent.running else {
            logs.append("提示：先启动 Agent 再上传照片")
            return
        }
        var params: [String: String] = [:]
        if let path = model.goproPlugin.lastPhotoLocalPath
            ?? model.serverPhotoPath
            ?? model.latestPhotoPath,
           !path.isEmpty {
            params["local_path"] = path
        } else if model.goproPlugin.lastPhotoData == nil {
            logs.append("没有可上传的照片，请先从 GoPro 或服务器下载")
            return
        }

        uploadBusy = true
        logs.append("GoPro Entry upload_photo \(params.keys.sorted())")
        Task { @MainActor in
            let result = await model.performGoPro(action: "upload_photo", params: params)
            logs.append(result.ok ? "上传完成" : "上传失败：\(result.message)")
        }
    }

    private func beginServerDownload() {
        guard !serverDownloadBusy else { return }
        guard model.edgeAgent.running else {
            logs.append("提示：先启动 Agent 再从服务器下载")
            return
        }

        serverDownloadBusy = true
        model.serverPhotoPath = nil
        previewError = ""
        logs.append("GoPro Entry download_latest_from_server")
        Task { @MainActor in
            let result = await model.performGoPro(action: "download_latest_from_server")
            logs.append(result.ok ? "服务器下载完成" : "服务器下载失败：\(result.message)")
        }
    }

    private func panel(_ kind: GoProPanelKind) -> some View {
        let response = snapshotBinding(for: kind)
        let intervalBinding = intervalBinding(for: kind)
        let scheduling = isScheduling(kind)
        let copyHint = copyHint(for: kind)
        let events = events(for: kind)

        return VStack(alignment: .leading, spacing: 10) {
            Text(kind.title)
                .font(.title3.weight(.semibold))

            VStack(alignment: .leading, spacing: 2) {
                Text(kind.urlLabel)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(kind.displayURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            HStack(spacing: 8) {
                Button {
                    if kind == .latest {
                        guard clicks.tryTap() else { return }
                        beginLatestDownload(force: false)
                    } else {
                        guard clicks.tryTap() else { return }
                        beginPanelAction(kind)
                    }
                } label: {
                    if kind == .latest, latestDownloadBusy {
                        Text("下载中…")
                    } else if kind == .status, statusBusy {
                        Text("查询中…")
                    } else if kind == .capture, captureBusy {
                        Text("拍照中…")
                    } else {
                        Text(kind.runButtonTitle)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(panelActionBusy(kind))

                if kind == .latest {
                    Button("预览照片") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        if model.latestPhotoPath == nil {
                            previewError = "请先下载最新照片"
                            logs.append(previewError)
                        } else {
                            previewError = ""
                            showLatestPhotoPreview = true
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(latestDownloadBusy || model.latestPhotoPath == nil)

                    Button(saveAlbumBusy ? "保存中…" : "保存到相册") {
                        guard clicks.tryTap() else { return }
                        saveToAlbum(path: model.latestPhotoPath)
                    }
                    .buttonStyle(.bordered)
                    .disabled(latestDownloadBusy || saveAlbumBusy || model.latestPhotoPath == nil)

                    if !previewError.isEmpty && model.latestPhotoPath == nil {
                        Text(previewError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                    if !saveAlbumHint.isEmpty {
                        Text(saveAlbumHint)
                            .font(.caption2)
                            .foregroundStyle(
                                saveAlbumHint.contains("失败") || saveAlbumHint.contains("未授权")
                                    ? .red : .green
                            )
                    }
                }

                if kind.supportsSchedule {
                    Picker("间隔", selection: intervalBinding) {
                        ForEach(ScheduleInterval.allCases) { interval in
                            Text(interval.label).tag(interval)
                        }
                    }
                    .pickerStyle(.menu)
                    .disabled(scheduling || panelActionBusy(kind))

                    Button(scheduling ? kind.scheduleOffTitle : kind.scheduleOnTitle) {
                        guard clicks.tryTap() else { return }
                        toggleSchedule(kind)
                    }
                    .buttonStyle(.bordered)
                    .tint(scheduling ? .orange : .accentColor)
                    .disabled(panelActionBusy(kind))
                }
            }
            .onChange(of: model.statusEvents.count) { _ in
                if kind == .status { statusBusy = false }
            }
            .onChange(of: model.captureEvents.count) { _ in
                if kind == .capture { captureBusy = false }
            }

            // Single-shot response (only from 查询状态 / 拍照 buttons)
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("接口返回")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    if !copyHint.isEmpty {
                        Text(copyHint)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Button("复制") {
                        copyResponse(kind)
                    }
                    .buttonStyle(.bordered)
                    .disabled(response.wrappedValue.isEmpty)
                }

                Text(response.wrappedValue.isEmpty ? "（暂无）" : response.wrappedValue)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(8)
                    .frame(minHeight: 80, alignment: .topLeading)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            // Unified execution event log for this panel
            VStack(alignment: .leading, spacing: 6) {
                Text(kind.eventsTitle)
                    .font(.subheadline.weight(.semibold))
                ScrollView {
                    if events.isEmpty {
                        Text("（暂无执行记录）")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(events) { event in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(event.timeText)
                                            .foregroundStyle(.secondary)
                                        Text(event.resultText)
                                            .foregroundStyle(event.ok ? .green : .red)
                                            .fontWeight(.semibold)
                                    }
                                    Text(event.body.isEmpty ? "（无返回内容）" : event.body)
                                        .foregroundStyle(.primary)
                                        .textSelection(.enabled)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .font(.system(.caption2, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .frame(height: 140)
                .padding(8)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var logPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("事件日志")
                .font(.subheadline.weight(.semibold))
            LazyVStack(alignment: .leading, spacing: 2) {
                ForEach(logs.lines, id: \.self) { line in
                    Text(line)
                        .font(.system(.caption2, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(8)
            .background(Color(.tertiarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    // MARK: - Bindings

    private func intervalBinding(for kind: GoProPanelKind) -> Binding<ScheduleInterval> {
        switch kind {
        case .status: return $statusInterval
        case .capture: return $captureInterval
        case .latest: return $statusInterval // unused; latest has no schedule
        }
    }

    private func snapshotBinding(for kind: GoProPanelKind) -> Binding<String> {
        switch kind {
        case .status: return $model.statusApiResponse
        case .capture: return $model.captureApiResponse
        case .latest: return $model.latestApiResponse
        }
    }

    private func events(for kind: GoProPanelKind) -> [GoProActionEvent] {
        switch kind {
        case .status: return model.statusEvents
        case .capture: return model.captureEvents
        case .latest: return model.latestEvents
        }
    }

    private func isScheduling(_ kind: GoProPanelKind) -> Bool {
        switch kind {
        case .status: return statusPolling
        case .capture: return captureScheduling
        case .latest: return false
        }
    }

    private func copyHint(for kind: GoProPanelKind) -> String {
        switch kind {
        case .status: return statusCopyHint
        case .capture: return captureCopyHint
        case .latest: return latestCopyHint
        }
    }

    private func copyResponse(_ kind: GoProPanelKind) {
        switch kind {
        case .status:
            UIPasteboard.general.string = model.statusApiResponse
            statusCopyHint = "已复制"
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { statusCopyHint = "" }
        case .capture:
            UIPasteboard.general.string = model.captureApiResponse
            captureCopyHint = "已复制"
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { captureCopyHint = "" }
        case .latest:
            UIPasteboard.general.string = model.latestApiResponse
            latestCopyHint = "已复制"
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { latestCopyHint = "" }
        }
    }

    // MARK: - Actions

    private func panelActionBusy(_ kind: GoProPanelKind) -> Bool {
        switch kind {
        case .status: return statusBusy
        case .capture: return captureBusy
        case .latest: return latestDownloadBusy
        }
    }

    private func beginPanelAction(_ kind: GoProPanelKind) {
        switch kind {
        case .status:
            guard !statusBusy else { return }
            statusBusy = true
        case .capture:
            guard !captureBusy else { return }
            captureBusy = true
        case .latest:
            break
        }
        let ok = run(kind, updateSnapshot: true)
        if !ok {
            switch kind {
            case .status: statusBusy = false
            case .capture: captureBusy = false
            case .latest: break
            }
        }
    }

    @discardableResult
    private func run(
        _ kind: GoProPanelKind,
        updateSnapshot: Bool,
        silentFailAgent: Bool = false,
        extraParams: [String: String] = [:]
    ) -> Bool {
        guard model.edgeAgent.running else {
            if !silentFailAgent {
                logs.append("提示：先启动 Agent 再执行 \(kind.title)")
            }
            return false
        }

        logs.append("GoPro Entry \(kind.actionName)")
        Task { @MainActor in
            let result = await model.performGoPro(
                action: kind.actionName,
                params: extraParams,
                updateSnapshot: updateSnapshot
            )
            logs.append(
                result.ok
                    ? "GoPro \(kind.actionName) 完成"
                    : "GoPro \(kind.actionName) 失败：\(result.message)"
            )
        }
        return true
    }

    /// Probe cache via plugin Entry; prompt if already present.
    private func beginLatestDownload(force: Bool) {
        guard !latestDownloadBusy else { return }

        latestDownloadBusy = true
        previewError = ""
        model.latestApiResponse = force ? "正在重新下载…" : "正在检查 / 下载最新照片…"
        logs.append(force ? "强制重新下载最新照片…" : "检查最新照片是否已下载…")

        Task { @MainActor in
            defer { latestDownloadBusy = false }
            var params: [String: String] = [:]
            if force { params["force"] = "true" }
            let result = await model.performGoPro(
                action: "latest_photo",
                params: params,
                updateSnapshot: true
            )
            if result.alreadyCached {
                redownloadPrompt = RedownloadPrompt(
                    name: result.cachedName ?? "photo",
                    timestamp: result.cachedTimestamp ?? "未知",
                    localPath: result.localPath ?? ""
                )
                showRedownloadConfirm = true
                logs.append("发现已下载：\(result.cachedName ?? "") ts=\(result.cachedTimestamp ?? "")")
            } else if result.ok {
                logs.append("下载完成：\(result.message)")
            } else {
                logs.append("下载失败：\(result.message)")
            }
        }
    }

    private func toggleSchedule(_ kind: GoProPanelKind) {
        switch kind {
        case .status:
            if statusPolling { stopStatusPolling(log: true) }
            else { startStatusPolling() }
        case .capture:
            if captureScheduling { stopCaptureSchedule(log: true) }
            else { startCaptureSchedule() }
        case .latest:
            break
        }
    }

    private func startStatusPolling() {
        guard model.edgeAgent.running else {
            logs.append("提示：先启动 Agent 再开启状态轮询")
            return
        }
        stopStatusPolling(log: false)
        statusPolling = true
        let interval = statusInterval
        logs.append("开启状态轮询 · 间隔 \(interval.label)")
        statusPollTask = Task { @MainActor in
            while !Task.isCancelled && statusPolling {
                _ = run(.status, updateSnapshot: false, silentFailAgent: true)
                if !model.edgeAgent.running {
                    logs.append("Agent 已停，自动关闭状态轮询")
                    stopStatusPolling(log: false)
                    break
                }
                try? await Task.sleep(nanoseconds: UInt64(interval.rawValue) * 1_000_000_000)
            }
        }
    }

    private func stopStatusPolling(log: Bool) {
        statusPollTask?.cancel()
        statusPollTask = nil
        if statusPolling {
            statusPolling = false
            if log { logs.append("关闭状态轮询") }
        }
    }

    private func startCaptureSchedule() {
        guard model.edgeAgent.running else {
            logs.append("提示：先启动 Agent 再开启定期拍照")
            return
        }
        stopCaptureSchedule(log: false)
        captureScheduling = true
        let interval = captureInterval
        logs.append("开启定期拍照 · 间隔 \(interval.label)")
        captureScheduleTask = Task { @MainActor in
            while !Task.isCancelled && captureScheduling {
                _ = run(.capture, updateSnapshot: false, silentFailAgent: true)
                if !model.edgeAgent.running {
                    logs.append("Agent 已停，自动关闭定期拍照")
                    stopCaptureSchedule(log: false)
                    break
                }
                try? await Task.sleep(nanoseconds: UInt64(interval.rawValue) * 1_000_000_000)
            }
        }
    }

    private func stopCaptureSchedule(log: Bool) {
        captureScheduleTask?.cancel()
        captureScheduleTask = nil
        if captureScheduling {
            captureScheduling = false
            if log { logs.append("关闭定期拍照") }
        }
    }

    private func wireAgentListener() {
        let bridge = AgentListenerBridge(logs: logs, tickLogs: tickLogs, model: model) { status in
            agentStatus = "Agent：\(model.edgeAgent.running ? "运行中" : "已停止") · \(status)"
        }
        model.edgeAgent.listener = bridge
        logs.bridge = bridge
    }
}

@MainActor
final class AgentTickLogStore: ObservableObject {
    @Published private(set) var heartbeatLines: [String] = []
    @Published private(set) var intentLines: [String] = []

    private let maxEntries = 5
    private let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    func appendHeartbeat(_ line: String) {
        append(line, to: \.heartbeatLines)
    }

    func appendIntent(_ line: String) {
        append(line, to: \.intentLines)
    }

    private func append(_ line: String, to keyPath: ReferenceWritableKeyPath<AgentTickLogStore, [String]>) {
        let stamped = "\(formatter.string(from: Date())) \(line)"
        self[keyPath: keyPath].append(stamped)
        if self[keyPath: keyPath].count > maxEntries {
            self[keyPath: keyPath].removeFirst(self[keyPath: keyPath].count - maxEntries)
        }
    }
}

@MainActor
final class LogStore: ObservableObject {
    @Published var lines: [String] = ["等待操作…"]
    var bridge: AgentListenerBridge?
    private var httpLogObserver: NSObjectProtocol?
    private var goProProgressObserver: NSObjectProtocol?
    private let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    init() {
        httpLogObserver = NotificationCenter.default.addObserver(
            forName: TimedHTTP.logNotification,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let line = note.userInfo?["line"] as? String else { return }
            // NotificationCenter callback is not MainActor-isolated; hop explicitly.
            Task { @MainActor in
                self?.append("[HTTP] \(line)")
            }
        }
        goProProgressObserver = NotificationCenter.default.addObserver(
            forName: .goProPipelineProgress,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let message = note.userInfo?["message"] as? String else { return }
            Task { @MainActor in
                self?.append(message)
            }
        }
    }

    deinit {
        if let httpLogObserver {
            NotificationCenter.default.removeObserver(httpLogObserver)
        }
        if let goProProgressObserver {
            NotificationCenter.default.removeObserver(goProProgressObserver)
        }
    }

    func append(_ line: String) {
        // Agent tick already surfaces heartbeat / intents-pull in dedicated boxes.
        if line.contains("[HTTP]") {
            let lower = line.lowercased()
            if lower.contains("edge-heartbeat") || lower.contains("intents-pull") {
                return
            }
        }
        let pieces = line
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        let chunks = pieces.isEmpty ? [line] : pieces
        if lines == ["等待操作…"] { lines = [] }
        for chunk in chunks {
            let stamped = "\(formatter.string(from: Date())) \(chunk)"
            lines.append(stamped)
        }
        if lines.count > 200 {
            lines.removeFirst(lines.count - 200)
        }
    }
}

@MainActor
final class AgentListenerBridge: EdgeAgentListener {
    private let logs: LogStore
    private let tickLogs: AgentTickLogStore
    private let model: AppModel
    private let onStatus: (String) -> Void

    init(
        logs: LogStore,
        tickLogs: AgentTickLogStore,
        model: AppModel,
        onStatus: @escaping (String) -> Void
    ) {
        self.logs = logs
        self.tickLogs = tickLogs
        self.model = model
        self.onStatus = onStatus
    }

    func onStatus(_ message: String) {
        onStatus(message)
        switch Self.classifyTickLog(message) {
        case .heartbeat:
            tickLogs.appendHeartbeat(message)
        case .intentPull:
            tickLogs.appendIntent(message)
        case .general:
            logs.append(message)
        }
    }

    private enum TickLogKind {
        case heartbeat
        case intentPull
        case general
    }

    /// Route Agent tick poll lines away from the bottom event log.
    private static func classifyTickLog(_ message: String) -> TickLogKind {
        let m = message
        if m.hasPrefix("Heartbeat ok")
            || m.contains("register/heartbeat failed")
            || m.hasPrefix("Tick failed:")
        {
            return .heartbeat
        }
        if m.hasPrefix("Intents pull")
            || m.hasPrefix("Pulled ")
            || m.hasPrefix("Commands pull failed")
            || m.hasPrefix("CommandHandler done server")
        {
            return .intentPull
        }
        return .general
    }

    func onPlansFetched(_ plans: [Plan]) {
        logs.append("拉取到 \(plans.count) 个 Plan: \(plans.map(\.planId).joined(separator: ", "))")
    }

    func onPlanFinished(_ outcome: PlanOutcome) {
        let mark = outcome.aborted ? "中止" : "完成"
        logs.append("Plan \(outcome.planId) \(mark) · \(outcome.reports.count) reports")
    }

    func onReport(_ report: ExecutionReport) {
        var line = "Report \(report.planId)/\(report.stepId) \(report.status.rawValue)"
        let message = report.message ?? ""
        if !message.isEmpty {
            line += " · \(message.prefix(120))"
        }
        let ok = report.status == .ok
        model.routeReport(planId: report.planId, ok: ok, message: message)
        logs.append(line)
    }

    func onEdgeInfoReported(_ info: EdgeNodeInfo) {
        model.lastEdgeInfo = info
        // Heartbeat tick already logs "Heartbeat ok …"; skip duplicate in bottom event log.
    }

    func onEdgeIdAssigned(_ edgeId: String) {
        logs.append("Brain 签发 edgeId=\(edgeId)")
    }
}

struct LatestPhotoPreviewSheet: View {
    let path: String?
    let onClose: () -> Void
    var onSave: (() -> Void)? = nil

    private var uiImage: UIImage? {
        guard let path, FileManager.default.fileExists(atPath: path) else { return nil }
        return UIImage(contentsOfFile: path)
    }

    var body: some View {
        NavigationStack {
            Group {
                if let uiImage {
                    ScrollView([.horizontal, .vertical]) {
                        Image(uiImage: uiImage)
                            .resizable()
                            .scaledToFit()
                            .frame(maxWidth: .infinity)
                            .padding()
                            .id(path ?? "")
                    }
                } else {
                    Text("无法加载照片\n\(path ?? "（无路径）")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(.systemBackground))
            .navigationTitle("照片预览")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if onSave != nil, uiImage != nil {
                        Button("保存到相册") { onSave?() }
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭", action: onClose)
                }
            }
        }
    }
}
