import SwiftUI

enum DevBrainChrome {
    static func tint(for mode: DevBrainEndpoint.Mode) -> Color {
        mode == .lan
            ? Color(red: 0.24, green: 0.84, blue: 0.55)
            : Color(red: 0.86, green: 0.48, blue: 0.16)
    }
}

/// Always-visible strip: actual Brain in use (not routing policy alone).
struct DevBrainEnvironmentStrip: View {
    @EnvironmentObject private var store: DevStore
    var onTap: () -> Void

    var body: some View {
        let env = store.brainEnvironment
        Button(action: onTap) {
            HStack(spacing: 10) {
                Circle()
                    .fill(DevBrainChrome.tint(for: env.mode))
                    .frame(width: 9, height: 9)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Brain · \(env.mode.displayName)")
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                    Text(env.activeBaseURL)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(env.routing.title)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.sand.opacity(0.85))
                if store.brainResolveBusy {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(DevTheme.sand)
                }
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(DevTheme.dim)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                DevBrainChrome.tint(for: env.mode).opacity(0.14)
                    .overlay(
                        Rectangle()
                            .frame(height: 1)
                            .foregroundStyle(DevTheme.panelStroke),
                        alignment: .bottom
                    )
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("当前 Brain \(env.mode.displayName)，连接方式 \(env.routing.title)")
    }
}

/// Brain strip + switcher sheet for tab root screens only (hidden on pushed detail pages).
struct DevTabRootLayout<Content: View>: View {
    @EnvironmentObject private var store: DevStore
    @State private var showBrainSwitcher = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(spacing: 0) {
            DevBrainEnvironmentStrip {
                showBrainSwitcher = true
            }
            content()
        }
        .sheet(isPresented: $showBrainSwitcher) {
            DevBrainRoutingSwitcherSheet()
                .environmentObject(store)
        }
    }
}

struct DevBrainEnvironmentCard: View {
    @EnvironmentObject private var store: DevStore
    @State private var showSwitcher = false

    var body: some View {
        let env = store.brainEnvironment
        DevPanel {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Circle()
                        .fill(DevBrainChrome.tint(for: env.mode))
                        .frame(width: 10, height: 10)
                    VStack(alignment: .leading, spacing: 4) {
                        DevTheme.sectionLabel("当前环境")
                        Text(env.mode.displayName)
                            .font(.system(size: 26, weight: .bold, design: .rounded))
                            .foregroundStyle(DevTheme.mist)
                    }
                    Spacer()
                    if store.brainResolveBusy {
                        ProgressView().tint(DevTheme.sand)
                    }
                }

                Text("Issue、Dev Task 都发到这个 Brain。")
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.dim)

                detailRow(label: "在用地址", value: env.activeBaseURL, mono: true)
                detailRow(label: "连接方式", value: env.routing.title)
                detailRow(
                    label: "本机网络",
                    value: env.looksOnHomeLAN
                        ? "家庭局域网（\(env.pathKind.label)）"
                        : "不在家庭局域网（\(env.pathKind.label)）"
                )
                detailRow(label: "局域网 Brain", value: probeLabel(env))
                if !env.lanProbeDetail.isEmpty {
                    Text(env.lanProbeDetail)
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(env.lanProbeOk == true ? DevTheme.ok : DevTheme.off)
                }

                Button {
                    showSwitcher = true
                } label: {
                    Text("更改连接方式…")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(DevTheme.sand))
                        .foregroundStyle(DevTheme.ink)
                }
                .buttonStyle(.plain)
            }
        }
        .sheet(isPresented: $showSwitcher) {
            DevBrainRoutingSwitcherSheet()
                .environmentObject(store)
        }
    }

    private func probeLabel(_ env: DevBrainEnvironment) -> String {
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
                .foregroundStyle(DevTheme.dim)
            Text(value)
                .font(mono
                    ? .system(size: 13, weight: .medium, design: .monospaced)
                    : .system(size: 13, weight: .medium, design: .rounded))
                .foregroundStyle(DevTheme.mist)
                .textSelection(.enabled)
        }
    }
}

struct DevBrainRoutingSwitcherSheet: View {
    @EnvironmentObject private var store: DevStore
    @Environment(\.dismiss) private var dismiss
    @State private var draft: DevBrainEndpoint.Routing = .auto

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                VStack(spacing: 0) {
                    currentBanner
                    List {
                        ForEach(DevBrainEndpoint.Routing.allCases) { route in
                            Button {
                                draft = route
                            } label: {
                                row(for: route)
                            }
                            .buttonStyle(.plain)
                            .listRowBackground(DevTheme.panel)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    confirmBar
                }
            }
            .navigationTitle("更改连接方式")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                        .foregroundStyle(DevTheme.sand)
                }
            }
            .onAppear { draft = store.brainRouting }
        }
        .presentationDetents([.medium, .large])
    }

    private var currentBanner: some View {
        let env = store.brainEnvironment
        return HStack(spacing: 10) {
            Circle()
                .fill(DevBrainChrome.tint(for: env.mode))
                .frame(width: 8, height: 8)
            Text("此刻实际连接：\(env.mode.displayName)")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.mist)
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(DevBrainChrome.tint(for: env.mode).opacity(0.14))
    }

    private func row(for route: DevBrainEndpoint.Routing) -> some View {
        let selected = draft == route
        let predicted = store.predictedBrainMode(for: route)
        return HStack(alignment: .top, spacing: 12) {
            Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 20))
                .foregroundStyle(selected ? DevTheme.sand : DevTheme.dim)
            VStack(alignment: .leading, spacing: 4) {
                Text(route.title)
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                Text(route.subtitle)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                    .fixedSize(horizontal: false, vertical: true)
                Text("确认后将连接到 \(predicted.displayName)  \(store.predictedBrainBase(for: route))")
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(DevBrainChrome.tint(for: predicted))
            }
        }
        .padding(.vertical, 4)
    }

    private var confirmBar: some View {
        let unchanged = draft == store.brainRouting
        let predicted = store.predictedBrainMode(for: draft)
        let warnLAN = draft == .lan && !store.brainEnvironment.looksOnHomeLAN
        return VStack(alignment: .leading, spacing: 10) {
            if warnLAN {
                Text("当前不像在家庭局域网，锁定局域网后可能连不上。")
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.off)
            }
            Button {
                guard !unchanged else {
                    dismiss()
                    return
                }
                store.applyBrainRouting(draft)
                dismiss()
            } label: {
                Text(unchanged ? "保持当前方式" : "确认切换到\(predicted.displayName)")
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(RoundedRectangle(cornerRadius: 12).fill(
                        unchanged ? DevTheme.chip : DevTheme.sand
                    ))
                    .foregroundStyle(unchanged ? DevTheme.mist : DevTheme.ink)
            }
            .buttonStyle(.plain)
            .disabled(store.brainResolveBusy)
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .padding(.bottom, 16)
    }
}
