import SwiftUI

struct NodeDetailView: View {
    let participantId: String
    @EnvironmentObject private var store: AdminStore

    var body: some View {
        ZStack {
            AdminTheme.ink.ignoresSafeArea()
            if let node = store.node(id: participantId) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        header(node)
                        roles(node)
                        capabilities(node)
                    }
                    .padding(16)
                    .padding(.bottom, 24)
                }
            } else {
                Text("节点已不在列表里")
                    .foregroundStyle(AdminTheme.dim)
            }
        }
        .navigationTitle(store.node(id: participantId)?.title ?? "节点")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(AdminTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .confirmationDialog(
            store.pendingDisable.map { "关掉 \($0.title)？" } ?? "确认关掉？",
            isPresented: disableDialogPresented,
            titleVisibility: .visible
        ) {
            Button("关掉", role: .destructive) {
                Task { await store.confirmPendingDisable() }
            }
            Button("取消", role: .cancel) {
                store.cancelPendingDisable()
            }
        } message: {
            Text("Brain 将不再把这类步骤派给这台设备。")
        }
    }

    private var disableDialogPresented: Binding<Bool> {
        Binding(
            get: { store.pendingDisable != nil },
            set: { if !$0 { store.cancelPendingDisable() } }
        )
    }

    private func header(_ node: AdminNode) -> some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                Text(node.shortId)
                    .font(.system(size: 13, weight: .medium, design: .monospaced))
                    .foregroundStyle(AdminTheme.dim)
                Text(node.registeredLabel)
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(AdminTheme.mist)
                Text(node.lastSeenLabel)
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(AdminTheme.mist)
            }
            Spacer()
            StatusPill(online: node.isOnline, label: node.statusLabel)
        }
    }

    private func roles(_ node: AdminNode) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            AdminTheme.sectionLabel("参与身份")
            if node.declaredRoles.isEmpty {
                Text("节点未声明任何身份")
                    .font(.system(size: 14, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            } else {
                ForEach(node.declaredRoles) { role in
                    SwitchRow(
                        title: role.title,
                        hint: role.hint,
                        isOn: role.enabled,
                        disabled: store.isBusy("\(node.participantId)|role|\(role.roleId)")
                    ) { on in
                        store.requestToggle(
                            participantId: node.participantId,
                            kind: .role,
                            targetId: role.roleId,
                            title: role.title,
                            enabled: on
                        )
                    }
                }
            }
            if !node.undeclaredRoleNames.isEmpty {
                Text("节点未声明：\(node.undeclaredRoleNames.joined(separator: "、"))")
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            }
        }
    }

    private func capabilities(_ node: AdminNode) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            AdminTheme.sectionLabel("可调度能力")
            if node.runtimeCapabilities.isEmpty {
                Text("没有 Runtime 能力")
                    .font(.system(size: 14, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            } else {
                ForEach(grouped(node.runtimeCapabilities)) { bucket in
                    if !bucket.group.isEmpty {
                        Text(bucket.group)
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(AdminTheme.mist)
                            .padding(.top, 4)
                    }
                    ForEach(bucket.items) { cap in
                        SwitchRow(
                            title: cap.capabilityId,
                            hint: cap.hint,
                            isOn: cap.enabled,
                            disabled: store.isBusy("\(node.participantId)|capability|\(cap.capabilityId)")
                        ) { on in
                            store.requestToggle(
                                participantId: node.participantId,
                                kind: .capability,
                                targetId: cap.capabilityId,
                                title: cap.capabilityId,
                                enabled: on
                            )
                        }
                    }
                }
            }
        }
    }

    private func grouped(_ caps: [AdminCapability]) -> [CapabilityGroup] {
        var order: [String] = []
        var map: [String: [AdminCapability]] = [:]
        for cap in caps {
            let key = cap.group
            if map[key] == nil {
                order.append(key)
                map[key] = []
            }
            map[key, default: []].append(cap)
        }
        return order.map { CapabilityGroup(group: $0, items: map[$0] ?? []) }
    }
}

private struct CapabilityGroup: Identifiable {
    var id: String { group.isEmpty ? "_" : group }
    let group: String
    let items: [AdminCapability]
}

struct SwitchRow: View {
    let title: String
    let hint: String
    let isOn: Bool
    let disabled: Bool
    let onChange: (Bool) -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 15, weight: .medium, design: .rounded))
                    .foregroundStyle(Color.white.opacity(0.92))
                Text(hint)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Toggle("", isOn: Binding(
                get: { isOn },
                set: { onChange($0) }
            ))
            .labelsHidden()
            .tint(AdminTheme.sand)
            .disabled(disabled)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(AdminTheme.chip)
        )
    }
}
