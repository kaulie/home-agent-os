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
                    VStack(alignment: .leading, spacing: 12) {
                        infoLine(
                            label: "最近一次",
                            value: Self.formatNodeTime(model.lastHeartbeatAt)
                        )
                        HStack(spacing: 8) {
                            if model.lastHeartbeatAt != nil {
                                Image(systemName: model.lastHeartbeatOk ? "checkmark.circle.fill" : "xmark.circle.fill")
                                    .foregroundStyle(model.lastHeartbeatOk ? Color.green : Color.red)
                                    .accessibilityLabel(model.lastHeartbeatOk ? "心跳成功" : "心跳失败")
                            }
                            Text(model.lastHeartbeatOk ? "成功" : (model.lastHeartbeatAt == nil ? "尚未心跳" : "失败"))
                                .font(.system(size: 13, weight: .medium, design: .rounded))
                                .foregroundStyle(EdgeTheme.mist)
                        }
                        infoLine(
                            label: "最近一次成功",
                            value: Self.formatNodeTime(model.lastHeartbeatSuccessAt)
                        )
                        if let nextAt = model.nextHeartbeatAt {
                            let sec = max(0, Int(ceil(nextAt.timeIntervalSince(context.date))))
                            let sending = (model.heartbeatBusy || model.brainResolveBusy) && sec == 0
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Text(sending ? "本次心跳" : "距离下次")
                                    .foregroundStyle(EdgeTheme.dim)
                                if sending {
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
                            .accessibilityLabel(sending ? "心跳发送中" : "距离下次心跳\(sec)秒")
                        }
                        if !model.lastHeartbeatOk, !model.lastHeartbeatError.isEmpty {
                            Text(model.lastHeartbeatError)
                                .font(.system(size: 12, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color.red.opacity(0.9))
                                .textSelection(.enabled)
                        }
                    }
                }
            }
        }
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
                        Text("【本地时间】\(Self.formatNodeTimeMs(sample.localAt))")
                            .font(.system(size: 13, weight: .regular, design: .monospaced))
                            .foregroundStyle(Color.white.opacity(0.9))
                            .textSelection(.enabled)
                        if let serverAt = sample.serverAt {
                            Text("【服务端时间】\(Self.formatNodeTimeMs(serverAt))")
                                .font(.system(size: 13, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color.white.opacity(0.9))
                                .textSelection(.enabled)
                        } else if model.clockSyncBusy {
                            Text("【服务端时间】…")
                                .font(.system(size: 13, weight: .regular, design: .monospaced))
                                .foregroundStyle(EdgeTheme.dim)
                        }
                        if let skewMs = sample.skewMs {
                            Text("【时差】\(Self.formatSkew(skewMs))")
                                .font(.system(size: 13, weight: .regular, design: .monospaced))
                                .foregroundStyle(Color.white.opacity(0.9))
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
                    infoLine(
                        label: "上报 role",
                        value: model.lastReportedRoles.isEmpty ? "—" : model.lastReportedRoles.joined(separator: ", ")
                    )
                    Text("变更（下次心跳）")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                        ForEach(ParticipantStore.allRoles, id: \.self) { role in
                            roleChip(role)
                        }
                    }
                    Text("点选只改下次心跳组包；上报 role 是上一次心跳请求里的 roles。")
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
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

    private static func formatSkew(_ skewMs: Int) -> String {
        if skewMs == 0 { return "0ms" }
        let absMs = abs(skewMs)
        let who = skewMs > 0 ? "服务端快" : "本机快"
        if absMs >= 1000 {
            return String(format: "%@ %.2fs (%+dms)", who, Double(absMs) / 1000.0, skewMs)
        }
        return "\(who) \(absMs)ms (\(skewMs >= 0 ? "+" : "")\(skewMs)ms)"
    }
}
