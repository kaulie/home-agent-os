import SwiftUI

struct DevConnectionView: View {
    @EnvironmentObject private var store: DevStore
    @FocusState private var focus: Field?

    private var lanResolvedCaption: String {
        if let ip = DevBrainEndpoint.lastSuccessfulLanHost {
            return "实际 IP：http://\(ip):9527"
        }
        return "实际 IP：尚未发现（点「重新扫描」）"
    }

    private enum Field {
        case lan
        case cloud
        case token
    }

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        DevBrainEnvironmentCard()

                        DevPanel {
                            VStack(alignment: .leading, spacing: 12) {
                                DevTheme.sectionLabel("局域网发现")
                                Text("局域网身份是 brain.local。在家 Wi‑Fi 时用 mDNS 发现并探测实际 IP；云端仍用固定 IP。")
                                    .font(.system(size: 12, design: .rounded))
                                    .foregroundStyle(DevTheme.dim)

                                if store.brainResolveBusy {
                                    HStack(spacing: 8) {
                                        ProgressView().tint(DevTheme.sand)
                                        Text(store.brainEnvironment.lanProbeDetail.isEmpty
                                            ? "正在解析 Brain…"
                                            : store.brainEnvironment.lanProbeDetail)
                                            .font(.system(size: 13, design: .rounded))
                                            .foregroundStyle(DevTheme.mist)
                                    }
                                } else if !store.brainEnvironment.lanProbeDetail.isEmpty {
                                    Text(store.brainEnvironment.lanProbeDetail)
                                        .font(.system(size: 13, design: .rounded))
                                        .foregroundStyle(
                                            store.brainEnvironment.lanProbeOk == true ? DevTheme.ok : DevTheme.off
                                        )
                                }

                                Button {
                                    Task { await store.rescanLANBrain() }
                                } label: {
                                    Text("重新扫描局域网 Brain")
                                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 10)
                                        .background(RoundedRectangle(cornerRadius: 10).fill(DevTheme.chip))
                                        .foregroundStyle(DevTheme.sand)
                                }
                                .buttonStyle(.plain)
                                .disabled(store.brainRouting == .cloud || store.brainResolveBusy)
                                .accessibilityIdentifier("dev.brain.rescan")
                            }
                        }

                        DevPanel {
                            VStack(alignment: .leading, spacing: 12) {
                                DevTheme.sectionLabel("地址槽")
                                Text("顶栏显示的是「当前实际连接」。改连接方式要点「更改连接方式」并确认，不会一碰就切走。")
                                    .font(.system(size: 12, design: .rounded))
                                    .foregroundStyle(DevTheme.dim)

                                field(title: "局域网 Brain", field: .lan) {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(DevBrainEndpoint.defaultLanBase)
                                            .font(.system(size: 14, design: .monospaced))
                                            .foregroundStyle(Color.white.opacity(0.92))
                                        Text(lanResolvedCaption)
                                            .font(.system(size: 12, design: .rounded))
                                            .foregroundStyle(DevTheme.dim)
                                    }
                                }

                                field(title: "云端 Brain", field: .cloud) {
                                    TextField(
                                        "",
                                        text: $store.cloudDraft,
                                        prompt: Text(DevBrainEndpoint.defaultCloudBase).foregroundColor(DevTheme.dim)
                                    )
                                    .textInputAutocapitalization(.never)
                                    .autocorrectionDisabled()
                                    .keyboardType(.URL)
                                    .focused($focus, equals: .cloud)
                                    .foregroundStyle(Color.white.opacity(0.92))
                                }
                            }
                        }

                        field(title: "管理员令牌", field: .token) {
                            SecureField(
                                "",
                                text: $store.tokenDraft,
                                prompt: Text("未设置则可空").foregroundColor(DevTheme.dim)
                            )
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .focused($focus, equals: .token)
                            .foregroundStyle(Color.white.opacity(0.92))
                        }

                        Button {
                            focus = nil
                            store.saveConnection()
                        } label: {
                            Text("保存地址与令牌")
                                .font(.system(size: 16, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.ink)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .fill(DevTheme.sand)
                                )
                        }

                        if let err = store.loadError, !err.isEmpty {
                            Text(err)
                                .font(.system(size: 13, design: .rounded))
                                .foregroundStyle(DevTheme.off)
                        }

                        Text("Dev Console：Issue、Dev Task、Chat、Fleet、Deploy。连接方式与 User Console（LivingRoomEdge）一致。")
                            .font(.system(size: 13, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                    .padding(16)
                }
            }
            .navigationTitle("连接")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private func field<Content: View>(
        title: String,
        field: Field,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.mist)
            content()
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(DevTheme.chip)
                )
        }
    }
}
