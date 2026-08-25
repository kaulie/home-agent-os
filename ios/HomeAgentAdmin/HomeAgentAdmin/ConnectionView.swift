import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var store: AdminStore
    @FocusState private var focus: Field?

    private enum Field {
        case brain
        case token
    }

    var body: some View {
        NavigationStack {
            ZStack {
                AdminTheme.ink.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        field(
                            title: "Brain",
                            placeholder: "直连 Brain，不走本机 8788。"
                        ) {
                            TextField(
                                "",
                                text: $store.brainDraft,
                                prompt: Text(AdminSettings.defaultBrainURL).foregroundColor(AdminTheme.dim)
                            )
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .keyboardType(.URL)
                                .focused($focus, equals: .brain)
                                .foregroundStyle(Color.white.opacity(0.92))
                        }

                        HStack(spacing: 10) {
                            presetButton(title: "局域网", url: AdminSettings.defaultBrainURL)
                            presetButton(title: "云", url: AdminSettings.cloudBrainURL)
                        }

                        field(
                            title: "管理员令牌",
                            placeholder: ""
                        ) {
                            SecureField(
                                "",
                                text: $store.tokenDraft,
                                prompt: Text("未设置则可空").foregroundColor(AdminTheme.dim)
                            )
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .focused($focus, equals: .token)
                                .foregroundStyle(Color.white.opacity(0.92))
                        }

                        Button {
                            focus = nil
                            Task { await store.saveConnectionAndRefresh() }
                        } label: {
                            Text(store.isLoading ? "正在刷新…" : "保存并刷新节点")
                                .font(.system(size: 16, weight: .semibold, design: .rounded))
                                .foregroundStyle(AdminTheme.ink)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .fill(AdminTheme.sand)
                                )
                        }
                        .disabled(store.isLoading)
                        .padding(.top, 4)

                        if let err = store.loadError, !err.isEmpty {
                            Text(err)
                                .font(.system(size: 13, design: .rounded))
                                .foregroundStyle(AdminTheme.off)
                        }

                        Text("没有直播、没有聊天、没有扫描。中控不发 intent。")
                            .font(.system(size: 13, design: .rounded))
                            .foregroundStyle(AdminTheme.dim)
                    }
                    .padding(16)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .navigationTitle("连接")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(AdminTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private func presetButton(title: String, url: String) -> some View {
        let selected = AdminSettings.normalize(store.brainDraft) == AdminSettings.normalize(url)
        return Button {
            store.brainDraft = url
        } label: {
            Text(title)
                .font(.system(size: 14, weight: .semibold, design: .rounded))
                .foregroundStyle(selected ? AdminTheme.ink : AdminTheme.sand)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(selected ? AdminTheme.sand : AdminTheme.chip)
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(AdminTheme.panelStroke, lineWidth: 1)
                        )
                )
        }
    }

    private func field<Content: View>(
        title: String,
        placeholder: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(AdminTheme.mist)
            content()
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(AdminTheme.chip)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(AdminTheme.panelStroke, lineWidth: 1)
                        )
                )
            if !placeholder.isEmpty {
                Text(placeholder)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            }
        }
    }
}
