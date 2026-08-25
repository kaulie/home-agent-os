import SwiftUI

enum BrainEnvironmentChrome {
    case form
    case dark
}

/// Always-on chip: which Brain is actually in use (not the routing policy).
struct BrainEnvironmentStrip: View {
    @EnvironmentObject private var model: AppModel
    var onTap: () -> Void

    var body: some View {
        let env = model.brainEnvironment
        Button(action: onTap) {
            HStack(spacing: 10) {
                Circle()
                    .fill(Self.tint(for: env.mode))
                    .frame(width: 9, height: 9)
                VStack(alignment: .leading, spacing: 1) {
                    Text("当前环境  \(env.mode.displayName)")
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.primary)
                    Text(env.activeBaseURL)
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(env.routing.title)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary)
                if model.brainResolveBusy {
                    ProgressView()
                        .controlSize(.mini)
                }
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Self.tint(for: env.mode).opacity(0.12))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("当前环境 \(env.mode.displayName)，连接方式 \(env.routing.title)")
        .accessibilityHint("点按可更改连接方式")
    }

    static func tint(for mode: BrainEndpoint.Mode) -> Color {
        mode == .lan
            ? Color(red: 0.16, green: 0.62, blue: 0.42)
            : Color(red: 0.86, green: 0.48, blue: 0.16)
    }
}

/// Status + deliberate switcher. Used on 节点 and in 设置.
struct BrainEnvironmentCard: View {
    var chrome: BrainEnvironmentChrome = .form
    var showProbeDetail: Bool = false
    @EnvironmentObject private var model: AppModel
    @State private var showSwitcher = false

    var body: some View {
        let env = model.brainEnvironment
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Circle()
                    .fill(BrainEnvironmentStrip.tint(for: env.mode))
                    .frame(width: 10, height: 10)
                VStack(alignment: .leading, spacing: 4) {
                    Text("当前环境")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(secondaryColor)
                    Text(env.mode.displayName)
                        .font(.system(size: chrome == .dark ? 28 : 22, weight: .bold, design: .rounded))
                        .foregroundStyle(primaryColor)
                }
                Spacer()
                if model.brainResolveBusy {
                    ProgressView()
                        .tint(chrome == .dark ? EdgeTheme.sand : Color.accentColor)
                        .controlSize(.small)
                }
            }

            Text("对话、心跳、注册都发到这里。")
                .font(.system(size: 12, weight: .regular, design: .rounded))
                .foregroundStyle(secondaryColor)

            detailRow(label: "在用地址", value: env.activeBaseURL, mono: true)
            detailRow(label: "连接方式", value: env.routing.title)
            detailRow(
                label: "本机网络",
                value: env.looksOnHomeLAN
                    ? "家庭局域网（\(env.pathKind.label)）"
                    : "不在家庭局域网（\(env.pathKind.label)）"
            )
            detailRow(label: "局域网 Brain", value: probeLabel(env))
            if showProbeDetail, !env.lanProbeDetail.isEmpty, env.lanProbeOk != true {
                Text(env.lanProbeDetail)
                    .font(.system(size: 12, weight: .regular, design: .monospaced))
                    .foregroundStyle(Color.orange)
                    .textSelection(.enabled)
            }

            Button {
                showSwitcher = true
            } label: {
                Text("更改连接方式…")
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .background(chrome == .dark ? EdgeTheme.sand : Color.accentColor)
                    .foregroundStyle(chrome == .dark ? EdgeTheme.ink : Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityHint("打开确认页后再切换，不会一碰就改")
        }
        .sheet(isPresented: $showSwitcher) {
            BrainRoutingSwitcherSheet()
                .environmentObject(model)
        }
    }

    private var primaryColor: Color {
        chrome == .dark ? Color.white.opacity(0.94) : Color.primary
    }

    private var secondaryColor: Color {
        chrome == .dark ? EdgeTheme.mist : Color.secondary
    }

    private func probeLabel(_ env: BrainNetworkEnvironment) -> String {
        switch env.lanProbeOk {
        case true: return "可达"
        case false: return "不可达"
        case nil: return "尚未探测"
        }
    }

    private func detailRow(label: String, value: String, mono: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(secondaryColor)
            Text(value)
                .font(mono
                    ? .system(size: 13, weight: .medium, design: .monospaced)
                    : .system(size: 13, weight: .medium, design: .rounded))
                .foregroundStyle(primaryColor)
                .textSelection(.enabled)
        }
    }
}

/// Two-step switcher: pick a policy, then confirm. Actual environment is previewed.
struct BrainRoutingSwitcherSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var draft: BrainEndpoint.Routing = .auto

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                currentBanner
                List {
                    ForEach(BrainEndpoint.Routing.allCases) { route in
                        Button {
                            draft = route
                        } label: {
                            row(for: route)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .listStyle(.insetGrouped)
                confirmBar
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("更改连接方式")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
            .onAppear { draft = model.brainRouting }
        }
        .presentationDetents([.medium, .large])
    }

    private var currentBanner: some View {
        let env = model.brainEnvironment
        return HStack(spacing: 10) {
            Circle()
                .fill(BrainEnvironmentStrip.tint(for: env.mode))
                .frame(width: 8, height: 8)
            Text("此刻实际连接：\(env.mode.displayName)")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(BrainEnvironmentStrip.tint(for: env.mode).opacity(0.12))
    }

    private func row(for route: BrainEndpoint.Routing) -> some View {
        let selected = draft == route
        let predicted = model.predictedBrainMode(for: route)
        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 20))
                .foregroundStyle(selected ? Color.accentColor : Color.secondary)
            VStack(alignment: .leading, spacing: 4) {
                Text(route.title)
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.primary)
                Text(route.subtitle)
                    .font(.system(size: 12, weight: .regular, design: .rounded))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text("确认后将连接到 \(predicted.displayName)  \(model.predictedBrainBase(for: route))")
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(BrainEnvironmentStrip.tint(for: predicted))
            }
        }
        .padding(.vertical, 4)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var confirmBar: some View {
        let unchanged = draft == model.brainRouting
        let predicted = model.predictedBrainMode(for: draft)
        let warnLAN = draft == .lan && !model.brainEnvironment.looksOnHomeLAN
        return VStack(alignment: .leading, spacing: 10) {
            if warnLAN {
                Text("当前不像在家庭局域网，锁定局域网后对话可能发不出去。")
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(.orange)
            }
            Button {
                guard !unchanged else {
                    dismiss()
                    return
                }
                model.applyBrainRouting(draft)
                dismiss()
            } label: {
                Text(unchanged ? "保持当前方式" : "确认切换到\(predicted.displayName)")
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(unchanged ? Color.secondary.opacity(0.25) : Color.accentColor)
                    .foregroundStyle(unchanged ? Color.primary : Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(model.brainResolveBusy)
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .padding(.bottom, 16)
    }
}
