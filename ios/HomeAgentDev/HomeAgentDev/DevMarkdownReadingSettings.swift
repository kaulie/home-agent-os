import SwiftUI

/// Soft, low-contrast palette for long-form Markdown reading (distinct from shell DevTheme.ink).
struct DevMarkdownReadingPalette {
    let canvas: Color
    let text: Color
    let heading: Color
    let headingMuted: Color
    let accent: Color
    let dim: Color
    let codeBackground: Color
    let codeBorder: Color
    let tableStripe: Color
    let quoteBar: Color

    static let paperDark = DevMarkdownReadingPalette(
        canvas: Color(red: 0.14, green: 0.15, blue: 0.17),
        text: Color(red: 0.82, green: 0.80, blue: 0.76),
        heading: Color(red: 0.90, green: 0.84, blue: 0.72),
        headingMuted: Color(red: 0.78, green: 0.76, blue: 0.72),
        accent: Color(red: 0.72, green: 0.62, blue: 0.46),
        dim: Color(red: 0.58, green: 0.56, blue: 0.52),
        codeBackground: Color(red: 0.18, green: 0.19, blue: 0.21),
        codeBorder: Color.white.opacity(0.06),
        tableStripe: Color.white.opacity(0.03),
        quoteBar: Color(red: 0.72, green: 0.62, blue: 0.46).opacity(0.45)
    )
}

struct DevMarkdownReadingStyle {
    var palette: DevMarkdownReadingPalette
    var fontScale: CGFloat
    var lineSpacing: CGFloat

    static let `default` = DevMarkdownReadingStyle(
        palette: .paperDark,
        fontScale: 1.0,
        lineSpacing: 5
    )

    func scaledBodySize(_ base: CGFloat) -> CGFloat { base * fontScale }
    func scaledLineSpacing() -> CGFloat { lineSpacing * fontScale }
}

private struct DevMarkdownReadingStyleKey: EnvironmentKey {
    static let defaultValue = DevMarkdownReadingStyle.default
}

extension EnvironmentValues {
    var devMarkdownReadingStyle: DevMarkdownReadingStyle {
        get { self[DevMarkdownReadingStyleKey.self] }
        set { self[DevMarkdownReadingStyleKey.self] = newValue }
    }
}

struct DevMarkdownOutlineItem: Identifiable, Equatable {
    let id: String
    let level: Int
    let title: String
}

enum DevMarkdownOutline {
    static func items(from blocks: [DevMarkdownBlock]) -> [DevMarkdownOutlineItem] {
        blocks.enumerated().compactMap { index, block in
            guard case .heading(let level, let inlines) = block, (1...3).contains(level) else { return nil }
            let title = DevMarkdownPlainText.from(inlines)
            guard !title.isEmpty else { return nil }
            return DevMarkdownOutlineItem(id: DevMarkdownAnchor.heading(index), level: level, title: title)
        }
    }
}

enum DevMarkdownAnchor {
    static func heading(_ blockIndex: Int) -> String { "md-heading-\(blockIndex)" }
}

enum DevMarkdownPlainText {
    static func from(_ inlines: [DevMarkdownInline]) -> String {
        inlines.map(\.text).joined()
    }
}

enum DevMarkdownFontScaleStore {
    static let key = "dev.markdown.fontScale"
    static let minScale: Double = 0.85
    static let maxScale: Double = 1.40
    static let step: Double = 0.05
    static let defaultScale: Double = 1.0

    static func clamp(_ value: Double) -> Double {
        min(maxScale, max(minScale, value))
    }

    static func label(for scale: Double) -> String {
        switch scale {
        case ..<0.93: return "小"
        case ..<1.07: return "中"
        case ..<1.20: return "大"
        default: return "特大"
        }
    }
}
