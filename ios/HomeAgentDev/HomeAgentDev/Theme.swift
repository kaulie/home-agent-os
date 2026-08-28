import SwiftUI

enum DevTheme {
    static let ink = Color(red: 0.05, green: 0.07, blue: 0.11)
    static let panel = Color(red: 0.10, green: 0.13, blue: 0.18)
    static let chip = Color(red: 0.14, green: 0.17, blue: 0.24)
    static let panelStroke = Color.white.opacity(0.08)
    static let sand = Color(red: 0.82, green: 0.70, blue: 0.48)
    static let mist = Color.white.opacity(0.72)
    static let dim = Color.white.opacity(0.42)
    static let ok = Color(red: 0.24, green: 0.84, blue: 0.55)
    static let off = Color(red: 0.77, green: 0.36, blue: 0.36)

    static func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold, design: .rounded))
            .tracking(1.2)
            .foregroundStyle(sand.opacity(0.85))
    }
}

struct DevPanel<Content: View>: View {
    var content: () -> Content

    init(@ViewBuilder content: @escaping () -> Content) {
        self.content = content
    }

    var body: some View {
        content()
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(DevTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(DevTheme.panelStroke, lineWidth: 1)
                    )
            )
    }
}
