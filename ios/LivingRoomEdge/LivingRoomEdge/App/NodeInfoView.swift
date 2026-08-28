import SwiftUI

/// Node identity, heartbeat, clock sync, and role toggles (formerly the chat top bar).
struct NodeInfoView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            ZStack {
                EdgeTheme.canvas
                ScrollView {
                    VStack(alignment: .leading, spacing: 28) {
                        VStack(alignment: .leading, spacing: 8) {
                            EdgeTheme.heroTitle("节点")
                            EdgeTheme.heroSubtitle("当前网络环境、心跳与对时。角色变更只影响下次心跳组包。")
                        }
                        .padding(.top, 8)

                        networkSection
                        identitySection
                        heartbeatSection
                        clockSection
                        rolesSection
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 36)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("节点")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .foregroundStyle(EdgeTheme.sand)
                    }
                    .accessibilityLabel("设置")
                }
            }
            .toolbarBackground(EdgeTheme.ink, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .sheet(isPresented: $showSettings) {
                ChatSettingsSheet()
                    .environmentObject(model)
            }
        }
    }

    private var networkSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("当前网络环境")
            EdgePanel {
                BrainEnvironmentCard(chrome: .dark, showProbeDetail: true)
            }
        }
    }

    private var identitySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("身份")
            EdgePanel {
                VStack(alignment: .leading, spacing: 14) {
                    infoLine(label: "本节点 id", value: model.participantId.isEmpty ? "未注册" : model.participantId)
                    infoLine(label: "注册时间", value: Self.formatNodeTime(model.registeredAt))
                    infoLine(label: "client_hint", value: model.clientHint)
                }
            }
        }
    }

    private var heartbeatSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("心跳")
            EdgePanel {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach([model.lanHeartbeat, model.cloudHeartbeat], id: \.mode) { status in
                            heartbeatRow(status)
                        }
                        Divider()
                            .background(EdgeTheme.dim.opacity(0.4))
                        if let nextAt = model.nextHeartbeatAt {
                            let sec = max(0, Int(ceil(nextAt.timeIntervalSince(context.date))))
                            let showSending = sec == 0
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Text(showSending ? "本次心跳" : "距离下次")
                                    .foregroundStyle(EdgeTheme.dim)
                                if showSending {
                                    ProgressView()
                                        .tint(EdgeTheme.sand)
                                        .controlSize(.small)
                                    Text("发送中")
                                        .font(.system(size: 22, weight: .bold, design: .rounded))
                                        .foregroundStyle(EdgeTheme.sand)
                                } else {
                                    Text("\(sec)")
                                        .font(.system(size: 28, weight: .bold, design: .rounded))
                                        .foregroundStyle(EdgeTheme.sand)
                                    Text("秒")
                                        .foregroundStyle(EdgeTheme.sand.opacity(0.85))
                                }
                            }
                            .accessibilityLabel(showSending ? "心跳发送中" : "距离下次心跳\(sec)秒")
                        }
                    }
                }
            }
        }
    }

    /// P0 dual-Brain: one row per Brain (LAN / Cloud). Active Brain is highlighted
    /// and tagged「当前」; minimal fields: 成功/失败 + 最近一次 + 最近成功 + 注册 + 错误.
    private func heartbeatRow(_ status: BrainHeartbeatStatus) -> some View {
        let active = status.mode == model.brainEnvironment.mode
        let baseURL = BrainEndpoint.displayBase(
            from: status.mode == .lan ? model.lanBrainURL : model.cloudBrainURL
        )
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if status.hasAttempted {
                    Image(systemName: status.lastOk ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(status.lastOk ? Color.green : Color.red)
                        .accessibilityLabel(status.lastOk ? "心跳成功" : "心跳失败")
                } else {
                    Circle()
                        .fill(EdgeTheme.dim.opacity(0.5))
                        .frame(width: 12, height: 12)
                        .accessibilityLabel("尚未心跳")
                }
                Text(status.mode.displayName)
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(EdgeTheme.mist)
                if active {
                    Text("当前")
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(EdgeTheme.ink)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(EdgeTheme.sand)
                        .clipShape(Capsule())
                }
                Spacer()
                Text(status.registered ? "已注册" : "未注册")
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(status.registered ? EdgeTheme.sand.opacity(0.9) : EdgeTheme.dim)
            }
            if let phaseLabel = status.phase.rowLabel {
                HStack(spacing: 6) {
                    ProgressView()
                        .tint(EdgeTheme.sand)
                        .controlSize(.small)
                    Text(phaseLabel)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.sand)
                }
                .accessibilityLabel(phaseLabel)
            }
            Text(baseURL)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
                .foregroundStyle(EdgeTheme.dim)
                .lineLimit(1)
                .truncationMode(.middle)
            infoLine(label: "最近一次", value: Self.formatNodeTime(status.lastAttemptAt))
            infoLine(label: "最近一次成功", value: Self.formatNodeTime(status.lastSuccessAt))
            if !status.lastOk, !status.lastError.isEmpty {
                Text(status.lastError)
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
                    .foregroundStyle(Color.red.opacity(0.9))
                    .textSelection(.enabled)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(active ? EdgeTheme.sand.opacity(0.08) : Color.clear)
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(active ? EdgeTheme.sand.opacity(0.4) : Color.clear, lineWidth: 1)
                )
        )
    }

    private var clockSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("对时")
            EdgePanel {
                VStack(alignment: .leading, spacing: 12) {
                    Button {
                        Task { await model.syncClock() }
                    } label: {
                        HStack(spacing: 8) {
                            if model.clockSyncBusy {
                                ProgressView()
                                    .tint(EdgeTheme.sand)
                                    .controlSize(.small)
                            }
                            Text(model.clockSyncBusy ? "对时中…" : "对时")
                                .font(.system(size: 15, weight: .semibold, design: .rounded))
                        }
                        .foregroundStyle(EdgeTheme.ink)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(EdgeTheme.sand)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(model.clockSyncBusy)

                    if let sample = model.clockSync {
                        clockTimeLine(label: "本地时间", value: Self.formatNodeTimeMs(sample.localAt))
                        clockTimeLine(
                            label: "LAN 服务器",
                            value: Self.clockServerLine(
                                at: sample.lanServerAt,
                                skewMs: sample.lanSkewMs,
                                busy: model.clockSyncBusy
                            )
                        )
                        if !sample.lanError.isEmpty {
                            Text(sample.lanError)
                                .font(.system(size: 11, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color.red.opacity(0.9))
                                .textSelection(.enabled)
                        }
                        clockTimeLine(
                            label: "Cloud 服务器",
                            value: Self.clockServerLine(
                                at: sample.cloudServerAt,
                                skewMs: sample.cloudSkewMs,
                                busy: model.clockSyncBusy
                            )
                        )
                        if !sample.cloudError.isEmpty {
                            Text(sample.cloudError)
                                .font(.system(size: 11, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color.red.opacity(0.9))
                                .textSelection(.enabled)
                        }
                    }
                    if !model.clockSyncError.isEmpty {
                        Text(model.clockSyncError)
                            .font(.system(size: 12, weight: .regular, design: .monospaced))
                            .foregroundStyle(Color.red.opacity(0.9))
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }

    private var rolesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("角色")
            EdgePanel {
                VStack(alignment: .leading, spacing: 14) {
                    reportedRolesRow(
                        mode: .lan,
                        roles: model.lanLastReportedRoles
                    )
                    reportedRolesRow(
                        mode: .cloud,
                        roles: model.cloudLastReportedRoles
                    )
                    Text("变更（下次心跳）")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                        ForEach(ParticipantStore.allRoles, id: \.self) { role in
                            roleChip(role)
                        }
                    }
                    Text("点选只改下次心跳组包；上报 role 是各 Brain 上一次成功心跳请求里的 roles。")
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
    }

    /// P0 dual-Brain: last roles actually sent to that Brain (LAN / Cloud).
    /// Chip toggles stay shared; only the acked 上报 display is split.
    private func reportedRolesRow(mode: BrainEndpoint.Mode, roles: [String]) -> some View {
        let active = mode == model.brainEnvironment.mode
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text(mode.displayName)
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(EdgeTheme.mist)
                if active {
                    Text("当前")
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(EdgeTheme.ink)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(EdgeTheme.sand)
                        .clipShape(Capsule())
                }
            }
            Text(roles.isEmpty ? "—" : roles.joined(separator: ", "))
                .font(.system(size: 15, weight: .medium, design: .monospaced))
                .foregroundStyle(Color.white.opacity(0.92))
                .textSelection(.enabled)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(active ? EdgeTheme.sand.opacity(0.08) : Color.clear)
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(active ? EdgeTheme.sand.opacity(0.4) : Color.clear, lineWidth: 1)
                )
        )
    }

    private func clockTimeLine(label: String, value: String) -> some View {
        Text("【\(label)】\(value)")
            .font(.system(size: 13, weight: .regular, design: .monospaced))
            .foregroundStyle(Color.white.opacity(0.9))
            .textSelection(.enabled)
    }

    private func infoLine(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(EdgeTheme.dim)
            Text(value)
                .font(.system(size: 15, weight: .medium, design: .monospaced))
                .foregroundStyle(Color.white.opacity(0.92))
                .textSelection(.enabled)
        }
    }

    private func roleChip(_ role: String) -> some View {
        let on = model.enabledRoles.contains(role)
        return Button {
            model.setRole(role, enabled: !on)
        } label: {
            Text(role)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(on ? EdgeTheme.sand : Color.white.opacity(0.06))
                .foregroundStyle(on ? EdgeTheme.ink : EdgeTheme.mist)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(role)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private static func formatNodeTime(_ date: Date?) -> String {
        guard let date else { return "—" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = TimeZone.current
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.string(from: date)
    }

    private static func formatNodeTimeMs(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = TimeZone.current
        f.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return f.string(from: date)
    }

    /// `skew_ms` = server − local. Shown next to the server wall clock.
    private static func clockServerLine(at: Date?, skewMs: Int?, busy: Bool) -> String {
        guard let at else { return busy ? "…" : "—" }
        let time = formatNodeTimeMs(at)
        guard let skewMs else { return time }
        return "\(time)  相对本地 \(formatSkewMs(skewMs))"
    }

    private static func formatSkewMs(_ ms: Int) -> String {
        if ms == 0 { return "0 ms" }
        return ms > 0 ? "+\(ms) ms" : "\(ms) ms"
    }
}
