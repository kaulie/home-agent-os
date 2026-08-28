import SwiftUI

struct FixRecommendationCardsView: View {
    let items: [FixRecommendationItem]
    let fallbackText: String

    var body: some View {
        if items.contains(where: \.isStructured) {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(items) { item in
                    FixRecommendationCard(item: item)
                }
            }
        } else if !fallbackText.isEmpty {
            DevSelectableText(text: fallbackText, color: Color.white.opacity(0.92))
        }
    }
}

private struct FixRecommendationCard: View {
    let item: FixRecommendationItem

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                DevSelectableText(
                    text: item.displayTitle,
                    weight: .semibold,
                    color: DevTheme.mist,
                    prominent: true
                )
                if !item.priority.isEmpty {
                    FixPriorityBadge(priority: item.priority)
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                if !item.owner.isEmpty {
                    FixFieldRow(label: "负责人", value: item.owner, mono: true)
                }
                if !item.purpose.isEmpty {
                    FixFieldRow(label: "作用", value: item.purpose)
                }
                if !item.expectedBenefit.isEmpty {
                    FixFieldRow(label: "预期收益", value: item.expectedBenefit)
                }
                if !item.approach.isEmpty {
                    FixFieldRow(label: "改法", value: item.approach)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(DevTheme.chip)
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(DevTheme.panelStroke, lineWidth: 1)
                )
        )
    }
}

private struct FixFieldRow: View {
    let label: String
    let value: String
    var mono: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.sand.opacity(0.85))
            DevSelectableText(
                text: value,
                mono: mono,
                color: DevTheme.mist
            )
        }
    }
}

private struct FixPriorityBadge: View {
    let priority: String

    private var normalized: String {
        priority
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased()
    }

    private var tint: Color {
        if normalized.hasPrefix("P0") || normalized.contains("高") {
            return DevTheme.off
        }
        if normalized.hasPrefix("P1") || normalized.contains("中") {
            return DevTheme.sand
        }
        return DevTheme.dim
    }

    var body: some View {
        Text(priority)
            .font(.system(size: 11, weight: .bold, design: .rounded))
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(tint.opacity(0.14))
            )
    }
}
