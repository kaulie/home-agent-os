import SwiftUI

/// Visual language for the four-pane Edge shell: night slate + warm sand.
enum EdgeTheme {
    static let ink = Color(red: 0.05, green: 0.07, blue: 0.11)
    static let panel = Color(red: 0.10, green: 0.13, blue: 0.18)
    static let panelStroke = Color.white.opacity(0.08)
    static let sand = Color(red: 0.82, green: 0.70, blue: 0.48)
    static let mist = Color.white.opacity(0.72)
    static let dim = Color.white.opacity(0.42)

    static var canvas: some View {
        ZStack {
            ink.ignoresSafeArea()
            RadialGradient(
                colors: [
                    Color(red: 0.18, green: 0.22, blue: 0.28).opacity(0.55),
                    ink.opacity(0),
                ],
                center: .topLeading,
                startRadius: 20,
                endRadius: 420
            )
            .ignoresSafeArea()
            LinearGradient(
                colors: [
                    Color(red: 0.22, green: 0.16, blue: 0.10).opacity(0.22),
                    .clear,
                ],
                startPoint: .bottomTrailing,
                endPoint: .center
            )
            .ignoresSafeArea()
        }
    }

    static func heroTitle(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 34, weight: .semibold, design: .serif))
            .foregroundStyle(Color.white.opacity(0.94))
            .tracking(-0.4)
    }

    static func heroSubtitle(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 14, weight: .regular, design: .rounded))
            .foregroundStyle(mist)
            .fixedSize(horizontal: false, vertical: true)
    }

    static func sectionLabel(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold, design: .rounded))
            .tracking(1.4)
            .foregroundStyle(sand.opacity(0.85))
    }
}

struct EdgePanel<Content: View>: View {
    var content: () -> Content

    init(@ViewBuilder content: @escaping () -> Content) {
        self.content = content
    }

    var body: some View {
        content()
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(EdgeTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 20, style: .continuous)
                            .stroke(EdgeTheme.panelStroke, lineWidth: 1)
                    )
            )
    }
}

struct EdgeEmptyPlaceholder: View {
    let title: String
    let detail: String

    var body: some View {
        EdgePanel {
            VStack(alignment: .leading, spacing: 10) {
                Text(title)
                    .font(.system(size: 18, weight: .semibold, design: .rounded))
                    .foregroundStyle(Color.white.opacity(0.9))
                Text(detail)
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
