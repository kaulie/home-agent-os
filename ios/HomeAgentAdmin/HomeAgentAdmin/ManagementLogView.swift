import SwiftUI

struct ManagementLogView: View {
    @EnvironmentObject private var store: AdminStore
    @State private var confirmClear = false

    var body: some View {
        NavigationStack {
            ZStack {
                AdminTheme.ink.ignoresSafeArea()
                VStack(spacing: 0) {
                    if let banner = store.logsBanner, !banner.isEmpty {
                        Text(banner)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(AdminTheme.off)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 10)
                    }
                    if store.logs.isEmpty {
                        Text(store.logsFromBrain
                             ? "还没有服务端操作记录。开关节点能力会出现在这里。"
                             : "还没有操作记录。开关节点能力会出现在这里。")
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(AdminTheme.dim)
                            .multilineTextAlignment(.center)
                            .padding(24)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        List {
                            ForEach(store.logs) { entry in
                                logRow(entry)
                                    .listRowBackground(AdminTheme.panel)
                                    .listRowSeparatorTint(AdminTheme.panelStroke)
                            }
                        }
                        .listStyle(.plain)
                        .scrollContentBackground(.hidden)
                    }
                }
            }
            .navigationTitle("管理")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(AdminTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    if !store.logsFromBrain {
                        Button("清空") { confirmClear = true }
                            .disabled(store.logs.isEmpty)
                            .foregroundStyle(store.logs.isEmpty ? AdminTheme.dim : AdminTheme.sand)
                    }
                }
            }
            .confirmationDialog("清空本机操作日志？", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("清空", role: .destructive) { store.clearLogs() }
                Button("取消", role: .cancel) {}
            } message: {
                Text("只清这台手机上的记录，不影响 Brain 策略。")
            }
            .task {
                await store.refreshLogs()
            }
            .refreshable {
                await store.refreshLogs()
            }
        }
    }

    private func logRow(_ entry: AdminLogEntry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(entry.kindLabel)
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundStyle(entry.kind == .error ? AdminTheme.off : AdminTheme.sand)
                Spacer()
                Text(entry.timeLabel)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            }
            Text(entry.summary)
                .font(.system(size: 15, weight: .medium, design: .rounded))
                .foregroundStyle(Color.white.opacity(0.92))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 6)
    }
}
