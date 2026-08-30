import SwiftUI

struct DevStatsView: View {
    @EnvironmentObject private var store: DevStore

    private let periodOptions: [(label: String, key: String)] = [
        ("今日", "day"),
        ("本周", "week"),
        ("本月", "month"),
        ("本年", "year"),
        ("全部", "all"),
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            periodPicker
                            if let err = store.statsError, !err.isEmpty {
                                Text(err)
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundStyle(DevTheme.off)
                            }
                            if store.isLoadingStats && store.statsUsage == nil {
                                ProgressView("加载统计…")
                                    .tint(DevTheme.sand)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 40)
                            } else if let stats = store.statsUsage {
                                summarySection(stats)
                                cloudCallsSection(stats)
                                timeSeriesSection(stats)
                                categorySection(stats.period)
                                footnote
                            }
                        }
                        .padding(16)
                    }
                }
            }
            .navigationTitle("统计")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .refreshable {
                await store.loadStats(showSpinner: false)
            }
        }
    }

    private var periodPicker: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("统计周期")
                LazyVGrid(
                    columns: [
                        GridItem(.flexible(), spacing: 8),
                        GridItem(.flexible(), spacing: 8),
                        GridItem(.flexible(), spacing: 8),
                    ],
                    spacing: 8
                ) {
                    ForEach(periodOptions, id: \.key) { option in
                        let selected = store.statsPeriod == option.key
                        Button {
                            store.statsPeriod = option.key
                            Task { await store.loadStats(showSpinner: true) }
                        } label: {
                            Text(option.label)
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .foregroundStyle(selected ? DevTheme.ink : DevTheme.sand)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 9)
                                .background(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(selected ? DevTheme.sand : DevTheme.chip)
                                )
                        }
                    }
                }
            }
        }
    }

    private func summarySection(_ stats: DevTokenUsageStats) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            DevTheme.sectionLabel("Token 总览")
            DevStatsUsageCard(
                title: stats.displayPeriodTitle,
                bucket: stats.period
            )
            if stats.allTime.totalTokens != stats.period.totalTokens || stats.periodKey == "all" {
                DevStatsUsageCard(title: "累计", bucket: stats.allTime)
            }
        }
    }

    private func cloudCallsSection(_ stats: DevTokenUsageStats) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                DevTheme.sectionLabel("云服务调用")
                let rows = stats.cloudCalls?.period ?? []
                if rows.isEmpty {
                    Text("该周期还没有记录")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else {
                    ForEach(rows) { row in
                        HStack(alignment: .firstTextBaseline) {
                            Text(row.label)
                                .font(.system(size: 14, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.mist)
                            Spacer(minLength: 8)
                            Text(row.count.formatted())
                                .font(.system(size: 15, weight: .bold, design: .monospaced))
                                .foregroundStyle(DevTheme.sand)
                            if row.fail > 0 {
                                Text("失败 \(row.fail.formatted())")
                                    .font(.system(size: 11, weight: .medium, design: .rounded))
                                    .foregroundStyle(DevTheme.off)
                            }
                        }
                        if row.id != rows.last?.id {
                            Divider().overlay(DevTheme.panelStroke)
                        }
                    }
                }
                Text("云调用从本 Brain 实例的埋点汇总；与 Cursor token 分开。火山语音识别来自 Mac STT，本机 say / 手机 AVSpeech 不算云调用。")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
        }
    }

    private func timeSeriesSection(_ stats: DevTokenUsageStats) -> some View {
        Group {
            if !stats.byTime.isEmpty {
                DevPanel {
                    VStack(alignment: .leading, spacing: 12) {
                        DevTheme.sectionLabel(stats.timeSectionLabel ?? "按时间")
                        let maxTokens = stats.byTime.map(\.totalTokens).max() ?? 1
                        ForEach(stats.byTime) { bucket in
                            DevStatsTimeRow(bucket: bucket, maxTokens: maxTokens)
                            if bucket.id != stats.byTime.last?.id {
                                Divider().overlay(DevTheme.panelStroke)
                            }
                        }
                    }
                }
            }
        }
    }

    private func categorySection(_ period: DevTokenUsageBucket) -> some View {
        Group {
            if let categories = period.byCategory, !categories.isEmpty {
                DevPanel {
                    VStack(alignment: .leading, spacing: 12) {
                        DevTheme.sectionLabel("按类别")
                        ForEach(categories) { row in
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(row.categoryLabel)
                                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                                        .foregroundStyle(DevTheme.mist)
                                    Text("\(row.taskCount) 次任务")
                                        .font(.system(size: 11, design: .rounded))
                                        .foregroundStyle(DevTheme.dim)
                                }
                                Spacer()
                                Text(row.compactLabel)
                                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                                    .foregroundStyle(DevTheme.sand)
                            }
                            if row.id != categories.last?.id {
                                Divider().overlay(DevTheme.panelStroke)
                            }
                        }
                    }
                }
            }
        }
    }

    private var footnote: some View {
        Text("数据来自 Cursor Agent 返回的 token 用量，按东八区日历划分今日/本周/本月/本年。仅统计本 Brain 实例上的 Dev Task。")
            .font(.system(size: 11, design: .rounded))
            .foregroundStyle(DevTheme.dim)
    }
}

struct DevStatsTimeRow: View {
    let bucket: DevTokenUsageTimeBucket
    let maxTokens: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(bucket.bucketLabel)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .frame(width: 52, alignment: .leading)
                GeometryReader { geo in
                    let width = maxTokens > 0
                        ? geo.size.width * CGFloat(bucket.totalTokens) / CGFloat(maxTokens)
                        : 0
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .fill(DevTheme.sand.opacity(0.85))
                        .frame(width: max(width, bucket.totalTokens > 0 ? 4 : 0), height: 10)
                }
                .frame(height: 10)
                Text("Σ \(bucket.totalTokens.formatted())")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(DevTheme.sand)
                    .frame(width: 72, alignment: .trailing)
            }
            Text("\(bucket.taskCount) 次 · ↑\(bucket.inputTokens.formatted()) ↓\(bucket.outputTokens.formatted())")
                .font(.system(size: 10, design: .rounded))
                .foregroundStyle(DevTheme.dim)
                .padding(.leading, 52)
        }
    }
}

struct DevStatsUsageCard: View {
    let title: String
    let bucket: DevTokenUsageBucket

    var body: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                Text(title)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                if bucket.totalTokens > 0 {
                    Text("Σ \(bucket.totalTokens.formatted())")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                        .foregroundStyle(DevTheme.sand)
                    Text("\(bucket.taskCount) 次任务")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                    HStack(spacing: 16) {
                        metric("输入", bucket.inputTokens)
                        metric("输出", bucket.outputTokens)
                        if bucket.cacheReadTokens > 0 {
                            metric("缓存读", bucket.cacheReadTokens)
                        }
                    }
                } else {
                    Text("该周期内还没有带 token 计量的完成任务。")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
            }
        }
    }

    private func metric(_ label: String, _ value: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 11, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            Text(value.formatted())
                .font(.system(size: 14, weight: .semibold, design: .monospaced))
                .foregroundStyle(DevTheme.mist)
        }
    }
}

extension DevTokenUsageBucket {
    var compactLabel: String {
        "↑\(inputTokens.formatted()) ↓\(outputTokens.formatted()) Σ\(totalTokens.formatted())"
    }
}

extension DevTokenUsageCategoryRow {
    var compactLabel: String {
        "↑\(inputTokens.formatted()) ↓\(outputTokens.formatted()) Σ\(totalTokens.formatted())"
    }
}
