import SwiftUI

struct EventStreamView: View {
    @EnvironmentObject private var store: AdminStore

    var body: some View {
        NavigationStack {
            ZStack {
                AdminTheme.ink.ignoresSafeArea()
                VStack(spacing: 0) {
                    if let err = store.intentsError, !err.isEmpty {
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
            .navigationTitle("事件流")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(AdminTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private var list: some View {
        List {
            if store.isLoadingIntents && store.intents.isEmpty {
                Text("加载中…")
                    .foregroundStyle(AdminTheme.dim)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else if store.intents.isEmpty {
                Text("还没有 Runtime 相关的 intent。发出命令后会按分钟刷新。")
                    .foregroundStyle(AdminTheme.dim)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            } else {
                ForEach(store.intents) { intent in
                    NavigationLink {
                        EventDetailView(intent: intent)
                    } label: {
                        EventRowView(intent: intent)
                    }
                    .listRowBackground(AdminTheme.panel)
                    .listRowSeparatorTint(AdminTheme.panelStroke)
                    .onAppear {
                        if intent.intentId == store.intents.last?.intentId,
                           !store.intentsExhausted,
                           !store.isLoadingIntents {
                            Task { await store.loadIntents(reset: false, showSpinner: false) }
                        }
                    }
                }
                if store.isLoadingIntents, !store.intents.isEmpty {
                    Text("加载更早的记录…")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(AdminTheme.dim)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .refreshable {
            await store.loadIntents(reset: true, showSpinner: false)
        }
    }
}

struct EventRowView: View {
    let intent: AdminIntent

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 8) {
                Circle()
                    .fill(dotColor)
                    .frame(width: 8, height: 8)
                Text(intent.statusTitle)
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .foregroundStyle(dotColor)
                Spacer()
                Text(intent.relativeLabel)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(AdminTheme.dim)
            }
            Text(intent.text.isEmpty ? "（无原文）" : intent.text)
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(Color.white.opacity(0.94))
                .lineLimit(3)
            Text(metaLine)
                .font(.system(size: 12, design: .rounded))
                .foregroundStyle(AdminTheme.dim)
                .lineLimit(2)
            Text(intent.resultText.isEmpty ? "尚无结果" : intent.resultText)
                .font(.system(size: 14, weight: .medium, design: .rounded))
                .foregroundStyle(intent.resultText.isEmpty ? AdminTheme.dim : AdminTheme.mist)
                .lineLimit(3)
        }
        .padding(.vertical, 6)
    }

    private var dotColor: Color {
        if intent.isFailure { return AdminTheme.off }
        if intent.isSuccess { return AdminTheme.ok }
        return AdminTheme.sand
    }

    private var metaLine: String {
        var bits: [String] = ["#\(intent.intentId)"]
        if !intent.issuerShort.isEmpty {
            bits.append("发出 \(intent.issuerShort)")
        }
        if !intent.runtimeShort.isEmpty {
            bits.append("执行 \(intent.runtimeShort)")
        }
        return bits.joined(separator: " · ")
    }
}

struct EventDetailView: View {
    let intent: AdminIntent

    var body: some View {
        ZStack {
            AdminTheme.ink.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    AdminPanel {
                        VStack(alignment: .leading, spacing: 8) {
                            AdminTheme.sectionLabel("原文")
                            Text(intent.text.isEmpty ? "（无原文）" : intent.text)
                                .font(.system(size: 17, weight: .semibold, design: .rounded))
                                .foregroundStyle(Color.white.opacity(0.94))
                            HStack {
                                Text(intent.statusTitle)
                                    .font(.system(size: 12, weight: .bold, design: .rounded))
                                    .foregroundStyle(dotColor)
                                Spacer()
                                Text(intent.timeLabel)
                                    .font(.system(size: 12, design: .rounded))
                                    .foregroundStyle(AdminTheme.dim)
                            }
                            if !intent.issuerShort.isEmpty {
                                Text("发出 \(intent.issuerShort)")
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundStyle(AdminTheme.mist)
                            }
                            if !intent.runtimeShort.isEmpty {
                                Text("执行 \(intent.runtimeShort)")
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundStyle(AdminTheme.mist)
                            }
                        }
                    }
                    AdminPanel {
                        VStack(alignment: .leading, spacing: 8) {
                            AdminTheme.sectionLabel("响应结果")
                            Text(intent.resultText.isEmpty ? "尚无结果" : intent.resultText)
                                .font(.system(size: 15, weight: .medium, design: .rounded))
                                .foregroundStyle(intent.resultText.isEmpty ? AdminTheme.dim : Color.white.opacity(0.92))
                            if !intent.presentation.type.isEmpty {
                                Text("类型 \(intent.presentation.type)")
                                    .font(.system(size: 12, design: .rounded))
                                    .foregroundStyle(AdminTheme.dim)
                            }
                        }
                    }
                    if !intent.executionPlan.isEmpty {
                        AdminPanel {
                            VStack(alignment: .leading, spacing: 12) {
                                AdminTheme.sectionLabel("执行步骤")
                                ForEach(intent.executionPlan) { step in
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Text(step.capability.isEmpty ? "（未知能力）" : step.capability)
                                                .font(.system(size: 14, weight: .semibold, design: .rounded))
                                                .foregroundStyle(Color.white.opacity(0.92))
                                            Spacer()
                                            Text(step.statusTitle)
                                                .font(.system(size: 12, weight: .bold, design: .rounded))
                                                .foregroundStyle(AdminTheme.sand)
                                        }
                                        if !step.assignedEdgeId.isEmpty {
                                            Text("边 \(AdminIntent.shortEdge(step.assignedEdgeId))")
                                                .font(.system(size: 12, design: .rounded))
                                                .foregroundStyle(AdminTheme.dim)
                                        }
                                        if !step.msg.isEmpty {
                                            Text(step.msg)
                                                .font(.system(size: 13, design: .rounded))
                                                .foregroundStyle(AdminTheme.off)
                                        }
                                        if !step.outputsPretty.isEmpty {
                                            Text(step.outputsPretty)
                                                .font(.system(size: 11, design: .monospaced))
                                                .foregroundStyle(AdminTheme.mist)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if !intent.statusLog.isEmpty {
                        AdminPanel {
                            VStack(alignment: .leading, spacing: 10) {
                                AdminTheme.sectionLabel("状态时间线")
                                ForEach(intent.statusLog) { event in
                                    HStack(alignment: .firstTextBaseline) {
                                        Text(event.status)
                                            .font(.system(size: 13, weight: .semibold, design: .rounded))
                                            .foregroundStyle(AdminTheme.sand)
                                        Spacer()
                                        if let ts = event.ts {
                                            Text(WireTime.absoluteLabel(ts))
                                                .font(.system(size: 12, design: .rounded))
                                                .foregroundStyle(AdminTheme.dim)
                                        }
                                    }
                                    if !event.msg.isEmpty {
                                        Text(event.msg)
                                            .font(.system(size: 13, design: .rounded))
                                            .foregroundStyle(AdminTheme.mist)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .navigationTitle("#\(intent.intentId)")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(AdminTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
    }

    private var dotColor: Color {
        if intent.isFailure { return AdminTheme.off }
        if intent.isSuccess { return AdminTheme.ok }
        return AdminTheme.sand
    }
}
