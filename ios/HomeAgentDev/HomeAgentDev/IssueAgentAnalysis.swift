import Foundation

/// Split Dev Agent debug-issue reply into root-cause vs fix recommendation.
struct IssueAgentAnalysisParts: Equatable {
    let rootCause: String
    let fixRecommendation: String
    let fixItems: [FixRecommendationItem]
    let hasExplicitSplit: Bool

    var hasStructuredFixItems: Bool {
        fixItems.contains(where: \.isStructured)
    }

    static let empty = IssueAgentAnalysisParts(
        rootCause: "",
        fixRecommendation: "",
        fixItems: [],
        hasExplicitSplit: false
    )
}

struct FixRecommendationItem: Identifiable, Equatable {
    let id: Int
    let title: String
    let priority: String
    let owner: String
    let purpose: String
    let expectedBenefit: String
    let approach: String

    var isStructured: Bool {
        !priority.isEmpty
            || !owner.isEmpty
            || !purpose.isEmpty
            || !expectedBenefit.isEmpty
            || !approach.isEmpty
    }

    var displayTitle: String {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return "建议 \(id + 1)"
        }
        return trimmed
    }
}

enum IssueAgentAnalysisParser {
    private static let fixMarkers = [
        "## 修复建议",
        "## 修复方案",
        "## 建议修复",
        "## 修复",
        "## Fix Recommendation",
        "## Recommended Fix",
        "## Fix",
    ]

    private static let rootMarkers = [
        "## 根因分析",
        "## 根因",
        "## Root Cause",
        "## 原因分析",
    ]

    static func parse(_ raw: String) -> IssueAgentAnalysisParts {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return .empty }

        if let split = split(at: fixMarkers, in: text) {
            let fixText = stripLeadingMarkers(from: split.trailing, markers: fixMarkers)
            return IssueAgentAnalysisParts(
                rootCause: stripLeadingMarkers(from: split.leading, markers: rootMarkers),
                fixRecommendation: fixText,
                fixItems: FixRecommendationParser.parse(fixText),
                hasExplicitSplit: true
            )
        }

        if let split = splitInlineLabels(in: text) {
            return IssueAgentAnalysisParts(
                rootCause: split.leading,
                fixRecommendation: split.trailing,
                fixItems: FixRecommendationParser.parse(split.trailing),
                hasExplicitSplit: true
            )
        }

        return IssueAgentAnalysisParts(
            rootCause: text,
            fixRecommendation: "",
            fixItems: [],
            hasExplicitSplit: false
        )
    }

    private static func split(at markers: [String], in text: String) -> (leading: String, trailing: String)? {
        var best: (range: Range<String.Index>, marker: String)?
        for marker in markers {
            if let range = text.range(of: marker, options: [.caseInsensitive, .diacriticInsensitive]) {
                if best == nil || range.lowerBound < best!.range.lowerBound {
                    best = (range, marker)
                }
            }
        }
        guard let hit = best else { return nil }
        let leading = String(text[..<hit.range.lowerBound])
        let trailingStart = hit.range.upperBound
        let trailing = String(text[trailingStart...])
        guard !leading.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !trailing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        return (leading, trailing)
    }

    private static func splitInlineLabels(in text: String) -> (leading: String, trailing: String)? {
        let labels = ["修复建议：", "修复建议:", "Fix recommendation:", "Recommended fix:"]
        for label in labels {
            if let range = text.range(of: label, options: [.caseInsensitive, .diacriticInsensitive]) {
                let leading = String(text[..<range.lowerBound])
                let trailing = String(text[range.upperBound...])
                if !leading.isEmpty, !trailing.isEmpty {
                    return (leading.trimmingCharacters(in: .whitespacesAndNewlines),
                            trailing.trimmingCharacters(in: .whitespacesAndNewlines))
                }
            }
        }
        return nil
    }

    private static func stripLeadingMarkers(from text: String, markers: [String]) -> String {
        var cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for marker in markers {
            if cleaned.range(of: marker, options: [.caseInsensitive, .diacriticInsensitive])?.lowerBound
                == cleaned.startIndex
                || cleaned.hasPrefix(marker) {
                if let range = cleaned.range(of: marker, options: [.caseInsensitive, .diacriticInsensitive]) {
                    cleaned = String(cleaned[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
                }
            }
        }
        return cleaned
    }
}

enum FixRecommendationParser {
    private struct FieldSpec {
        let labels: [String]
        let keyPath: WritableKeyPath<MutableItem, String>
    }

    private struct MutableItem {
        var title = ""
        var priority = ""
        var owner = ""
        var purpose = ""
        var expectedBenefit = ""
        var approach = ""
        var leftoverLines: [String] = []

        var isStructured: Bool {
            !priority.isEmpty
                || !owner.isEmpty
                || !purpose.isEmpty
                || !expectedBenefit.isEmpty
                || !approach.isEmpty
        }
    }

    private static let fieldSpecs: [FieldSpec] = [
        FieldSpec(labels: ["优先级", "Priority"], keyPath: \.priority),
        FieldSpec(labels: ["负责人", "Owner", "负责方"], keyPath: \.owner),
        FieldSpec(labels: ["作用", "Purpose", "目的"], keyPath: \.purpose),
        FieldSpec(labels: ["预期收益", "Expected benefit", "收益", "预期效果"], keyPath: \.expectedBenefit),
        FieldSpec(labels: ["改法", "具体改法", "修复步骤", "步骤", "Fix", "Implementation"], keyPath: \.approach),
    ]

    static func parse(_ text: String) -> [FixRecommendationItem] {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }

        let blocks = splitIntoBlocks(trimmed)
        let items = blocks.enumerated().compactMap { index, block -> FixRecommendationItem? in
            let parsed = parseBlock(block)
            guard parsed.isStructured || !parsed.title.isEmpty || !parsed.leftoverLines.isEmpty else {
                return nil
            }
            var approach = parsed.approach
            if approach.isEmpty, !parsed.leftoverLines.isEmpty {
                approach = parsed.leftoverLines.joined(separator: "\n")
            }
            return FixRecommendationItem(
                id: index,
                title: parsed.title,
                priority: parsed.priority,
                owner: parsed.owner,
                purpose: parsed.purpose,
                expectedBenefit: parsed.expectedBenefit,
                approach: approach
            )
        }

        if items.isEmpty {
            return [FixRecommendationItem(
                id: 0,
                title: "",
                priority: "",
                owner: "",
                purpose: "",
                expectedBenefit: "",
                approach: trimmed
            )]
        }
        return items
    }

    private static func splitIntoBlocks(_ text: String) -> [String] {
        var blocks: [String] = []
        var current: [String] = []

        for line in text.components(separatedBy: .newlines) {
            if isItemHeader(line), !current.isEmpty {
                blocks.append(current.joined(separator: "\n"))
                current = [line]
            } else {
                current.append(line)
            }
        }
        if !current.isEmpty {
            blocks.append(current.joined(separator: "\n"))
        }

        if blocks.count == 1 {
            let separated = text.components(separatedBy: "\n---\n")
            if separated.count > 1 {
                return separated
            }
        }
        return blocks
    }

    private static func isItemHeader(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("### ") { return true }
        if trimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) != nil { return true }
        if trimmed.hasPrefix("**建议") && trimmed.contains("**") { return true }
        return false
    }

    private static func parseBlock(_ block: String) -> MutableItem {
        var item = MutableItem()
        let lines = block.components(separatedBy: .newlines)
        var bodyLines: [String] = []

        for (index, rawLine) in lines.enumerated() {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }

            if index == 0 || (item.title.isEmpty && isItemHeader(rawLine)) {
                if let title = parseTitle(from: line) {
                    item.title = title
                    continue
                }
            }

            if let (spec, value) = parseFieldLine(line) {
                item[keyPath: spec.keyPath] = value
                continue
            }

            bodyLines.append(rawLine)
        }

        item.leftoverLines = bodyLines
        return item
    }

    private static func parseTitle(from line: String) -> String? {
        var text = stripMarkdownDecorations(line)

        if text.hasPrefix("### ") {
            text = String(text.dropFirst(4))
        }

        if let match = text.range(of: #"^\d+\.\s*"#, options: .regularExpression) {
            text = String(text[match.upperBound...])
        }

        if let range = text.range(of: #"^建议\s*\d+\s*[:：]\s*"#, options: .regularExpression) {
            text = String(text[range.upperBound...])
        }

        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private static func parseFieldLine(_ line: String) -> (FieldSpec, String)? {
        var text = stripMarkdownDecorations(line)
        if text.hasPrefix("- ") { text = String(text.dropFirst(2)) }
        if text.hasPrefix("* ") { text = String(text.dropFirst(2)) }
        if text.hasPrefix("• ") { text = String(text.dropFirst(2)) }
        text = text.trimmingCharacters(in: .whitespaces)

        for spec in fieldSpecs {
            for label in spec.labels {
                for separator in ["：", ":"] {
                    let prefix = "\(label)\(separator)"
                    if text.range(of: prefix, options: [.caseInsensitive, .diacriticInsensitive])?.lowerBound == text.startIndex {
                        let value = String(text.dropFirst(prefix.count))
                            .trimmingCharacters(in: .whitespacesAndNewlines)
                        return (spec, value)
                    }
                }
            }
        }
        return nil
    }

    private static func stripMarkdownDecorations(_ line: String) -> String {
        line
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "__", with: "")
            .trimmingCharacters(in: .whitespaces)
    }
}
