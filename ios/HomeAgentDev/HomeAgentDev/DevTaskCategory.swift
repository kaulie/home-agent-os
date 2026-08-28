import SwiftUI

struct DevTaskCategory: Identifiable, Equatable {
    let id: String
    let label: String

    static let all: [DevTaskCategory] = [
        DevTaskCategory(id: "bug_fix", label: "Issue 跟进"),
        DevTaskCategory(id: "feature", label: "功能开发"),
        DevTaskCategory(id: "tech_discuss", label: "技术探讨"),
        DevTaskCategory(id: "ops", label: "运维部署"),
        DevTaskCategory(id: "chat", label: "闲聊"),
        DevTaskCategory(id: "other", label: "其他"),
    ]

    static let filterAll = DevTaskCategory(id: "", label: "全部")

    static func find(id: String) -> DevTaskCategory {
        let key = id.trimmingCharacters(in: .whitespacesAndNewlines)
        return all.first(where: { $0.id == key }) ?? DevTaskCategory(id: "other", label: "其他")
    }
}

struct DevCategoryBadge: View {
    let categoryId: String
    let categoryLabel: String
    var prominent: Bool = false

    private var tint: Color {
        switch categoryId {
        case "bug_fix": return DevTheme.off
        case "feature": return DevTheme.sand
        case "tech_discuss": return Color(red: 0.45, green: 0.72, blue: 0.98)
        case "ops": return Color(red: 0.62, green: 0.55, blue: 0.92)
        case "chat": return DevTheme.ok
        default: return DevTheme.dim
        }
    }

    var body: some View {
        Text(categoryLabel)
            .font(.system(size: prominent ? 13 : 11, weight: .bold, design: .rounded))
            .foregroundStyle(tint)
            .padding(.horizontal, prominent ? 12 : 8)
            .padding(.vertical, prominent ? 6 : 3)
            .background(
                Capsule()
                    .fill(tint.opacity(prominent ? 0.22 : 0.16))
                    .overlay(
                        Capsule().stroke(tint.opacity(0.35), lineWidth: prominent ? 1 : 0)
                    )
            )
    }
}

struct DevCategoryPickerGrid: View {
    @Binding var selection: String

    private let columns = [
        GridItem(.flexible(), spacing: 10),
        GridItem(.flexible(), spacing: 10),
    ]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 10) {
            ForEach(DevTaskCategory.all) { cat in
                let selected = selection == cat.id
                let tint = badgeTint(cat.id)
                Button {
                    selection = cat.id
                } label: {
                    Text(cat.label)
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(selected ? DevTheme.ink : DevTheme.mist)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(selected ? tint : tint.opacity(0.12))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .stroke(selected ? tint.opacity(0.5) : DevTheme.panelStroke, lineWidth: 1)
                                )
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func badgeTint(_ id: String) -> Color {
        switch id {
        case "bug_fix": return DevTheme.off
        case "feature": return DevTheme.sand
        case "tech_discuss": return Color(red: 0.45, green: 0.72, blue: 0.98)
        case "ops": return Color(red: 0.62, green: 0.55, blue: 0.92)
        case "chat": return DevTheme.ok
        default: return DevTheme.dim
        }
    }
}

struct DevCategoryChipRow: View {
    @Binding var selection: String
    var includeAll: Bool = false

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                if includeAll {
                    chip(DevTaskCategory.filterAll)
                }
                ForEach(DevTaskCategory.all) { cat in
                    chip(cat)
                }
            }
            .padding(.horizontal, 2)
        }
    }

    private func chip(_ cat: DevTaskCategory) -> some View {
        let selected = selection == cat.id
        let tint = badgeTint(cat.id)
        return Button {
            selection = cat.id
        } label: {
            Text(cat.label)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(selected ? DevTheme.ink : tint)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    Capsule()
                        .fill(selected ? tint : tint.opacity(0.14))
                )
        }
        .buttonStyle(.plain)
    }

    private func badgeTint(_ id: String) -> Color {
        switch id {
        case "bug_fix": return DevTheme.off
        case "feature": return DevTheme.sand
        case "tech_discuss": return Color(red: 0.45, green: 0.72, blue: 0.98)
        case "ops": return Color(red: 0.62, green: 0.55, blue: 0.92)
        case "chat": return DevTheme.ok
        case "": return DevTheme.mist
        default: return DevTheme.dim
        }
    }
}
