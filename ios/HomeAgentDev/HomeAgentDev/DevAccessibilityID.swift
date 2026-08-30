import Foundation

/// Stable accessibility identifiers for XCUITest (@quality). Do not rename without coordinating.
enum DevAccessibilityID {
    static let tabDocs = "dev.tab.docs"

    static let docsList = "dev.docs.list"
    static func docsRow(path: String) -> String {
        "dev.docs.row.\(path.replacingOccurrences(of: "/", with: "."))"
    }
    static let docsDetail = "dev.docs.detail"

    static let markdownReader = "dev.markdown.reader"
    static let markdownTOC = "dev.markdown.toc"
    static let markdownFontSmaller = "dev.markdown.font.smaller"
    static let markdownFontLarger = "dev.markdown.font.larger"
    static let markdownFontLabel = "dev.markdown.font.label"
    static let markdownTOCSheet = "dev.markdown.toc.sheet"
    static func markdownTOCItem(index: Int) -> String {
        "dev.markdown.toc.item.\(index)"
    }

    static let chatMic = "chat.mic"
}
