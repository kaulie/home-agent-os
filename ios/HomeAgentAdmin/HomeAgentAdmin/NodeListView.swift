import SwiftUI

struct NodeListView: View {
    @EnvironmentObject private var store: AdminStore

    var body: some View {
        NavigationStack {
            ZStack {
                AdminTheme.ink.ignoresSafeArea()
                VStack(spacing: 0) {
                    filterBar
                    if let err = store.loadError, !err.isEmpty {
                        Text(err)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(AdminTheme.off)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 10)
                    }
                    list
                }
            }
            .navigationTitle("节点")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(AdminTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private var filterBar: some View {
        HStack(spacing: 8) {
            ForEach(OnlineFilter.allCases) { item in
                let on = store.filter == item
                Button {
                    store.filter = item
                } label: {
                    Text(item.title)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(on ? AdminTheme.ink : AdminTheme.mist)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(
                            Capsule(style: .continuous)
                                .fill(on ? AdminTheme.sand : AdminTheme.chip)
                        )
                }
                .buttonStyle(.plain)
            }
            Spacer()
            Text("\(store.filteredNodes.count)")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(AdminTheme.dim)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var list: some View {
        List {
            if store.isLoading && store.nodes.isEmpty {
                Text("加载中…")
                    .foregroundStyle(AdminTheme.dim)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else if store.filteredNodes.isEmpty {
                Text(emptyCopy)
                    .foregroundStyle(AdminTheme.dim)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else {
                ForEach(store.filteredNodes) { node in
                    NavigationLink(value: node.participantId) {
                        NodeRowView(node: node)
                    }
                    .listRowBackground(AdminTheme.panel)
                    .listRowSeparatorTint(AdminTheme.panelStroke)
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .refreshable {
            await store.load(showSpinner: false)
        }
        .navigationDestination(for: String.self) { pid in
            NodeDetailView(participantId: pid)
        }
    }

    private var emptyCopy: String {
        switch store.filter {
        case .online: return "现在没有在线节点"
        case .offline: return "没有离线节点"
        case .never: return "没有未心跳节点"
        }
    }
}

struct NodeRowView: View {
    let node: AdminNode

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(node.title)
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.white.opacity(0.94))
                Text("\(node.kindLine) · \(node.runtimeCapabilities.count) 项能力 · \(node.lastSeenLabel)")
                    .font(.system(size: 12, weight: .regular, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
                    .lineLimit(2)
                Text(node.registeredLabel)
                    .font(.system(size: 12, weight: .regular, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            }
            Spacer(minLength: 8)
            StatusPill(online: node.isOnline, label: node.statusLabel)
        }
        .padding(.vertical, 6)
    }
}

struct StatusPill: View {
    let online: Bool
    let label: String

    var body: some View {
        Text(label)
            .font(.system(size: 11, weight: .bold, design: .rounded))
            .foregroundStyle(online ? AdminTheme.ok : AdminTheme.dim)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule(style: .continuous)
                    .fill(online ? AdminTheme.ok.opacity(0.16) : Color.white.opacity(0.06))
            )
    }
}
