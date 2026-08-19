import SwiftUI

/// Lightweight dismissible overlay for one user turn's logistics timeline.
struct IntentProgressOverlay: View {
    let journey: IntentJourney
    let onClose: () -> Void

    var body: some View {
        ZStack {
            Color.black.opacity(0.32)
                .ignoresSafeArea()
                .onTapGesture(perform: onClose)

            VStack(spacing: 0) {
                HStack(alignment: .center, spacing: 8) {
                    Text("执行进度")
                        .font(.headline)
                    Spacer()
                    if !journey.idle {
                        statusChip
                    }
                    Button(action: onClose) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityLabel("关闭")
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 8)

                ScrollView {
                    IntentLogisticsTimelineView(journey: journey, embedded: true)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 16)
                }
            }
            .frame(maxWidth: 440)
            .frame(maxHeight: 520)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: .black.opacity(0.22), radius: 18, y: 8)
            .padding(.horizontal, 20)
            .padding(.vertical, 28)
        }
        .transition(.opacity.combined(with: .scale(scale: 0.98)))
    }

    private var statusChip: some View {
        Text(chipLabel)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(chipColor)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(chipColor.opacity(0.14))
            .clipShape(Capsule())
    }

    private var chipLabel: String {
        if journey.current == .failed { return "失败" }
        if journey.timedOut { return "等待中" }
        if journey.terminal { return "完成" }
        return "进行中"
    }

    private var chipColor: Color {
        if journey.current == .failed { return .red }
        if journey.timedOut { return .orange }
        if journey.terminal { return .green }
        return .orange
    }
}
