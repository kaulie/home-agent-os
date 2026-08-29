import Foundation

enum DevMarkdownInlineStyle: Equatable {
    case plain
    case bold
    case italic
    case code
    case link(url: String)
}

struct DevMarkdownInline: Equatable {
    let text: String
    let style: DevMarkdownInlineStyle
}

enum DevMarkdownBlock: Identifiable, Equatable {
    case heading(level: Int, inlines: [DevMarkdownInline])
    case paragraph(inlines: [DevMarkdownInline])
    case unorderedList(items: [[DevMarkdownInline]])
    case orderedList(items: [[DevMarkdownInline]])
    case codeBlock(language: String?, code: String)
    case blockquote(blocks: [DevMarkdownBlock])
    case table(headers: [String], rows: [[String]])
    case divider

    var id: String {
        switch self {
        case .heading(let level, let inlines):
            return "h\(level)-\(inlines.map(\.text).joined())"
        case .paragraph(let inlines):
            return "p-\(inlines.map(\.text).joined())"
        case .unorderedList(let items):
            return "ul-\(items.count)-\(items.first?.first?.text ?? "")"
        case .orderedList(let items):
            return "ol-\(items.count)-\(items.first?.first?.text ?? "")"
        case .codeBlock(let lang, let code):
            return "code-\(lang ?? "")-\(code.prefix(24))"
        case .blockquote(let blocks):
            return "quote-\(blocks.count)"
        case .table(let headers, let rows):
            return "table-\(headers.joined())-\(rows.count)"
        case .divider:
            return "hr-\(UUID().uuidString)"
        }
    }
}

enum DevMarkdownParser {
    static func parse(_ markdown: String) -> [DevMarkdownBlock] {
        let lines = markdown.components(separatedBy: .newlines)
        var blocks: [DevMarkdownBlock] = []
        var index = 0

        while index < lines.count {
            let line = lines[index]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.isEmpty {
                index += 1
                continue
            }

            if trimmed.hasPrefix("```") {
                let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                index += 1
                var codeLines: [String] = []
                while index < lines.count, !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                    codeLines.append(lines[index])
                    index += 1
                }
                if index < lines.count { index += 1 }
                blocks.append(.codeBlock(language: language.isEmpty ? nil : language, code: codeLines.joined(separator: "\n")))
                continue
            }

            if isDivider(trimmed) {
                blocks.append(.divider)
                index += 1
                continue
            }

            if let level = headingLevel(trimmed) {
                let text = String(trimmed.dropFirst(level + 1))
                blocks.append(.heading(level: level, inlines: parseInline(text)))
                index += 1
                continue
            }

            if trimmed.hasPrefix(">") {
                var quoteLines: [String] = []
                while index < lines.count {
                    let q = lines[index].trimmingCharacters(in: .whitespaces)
                    guard q.hasPrefix(">") else { break }
                    let body = q.dropFirst().trimmingCharacters(in: .whitespaces)
                    quoteLines.append(String(body))
                    index += 1
                }
                let inner = parse(quoteLines.joined(separator: "\n"))
                blocks.append(.blockquote(blocks: inner.isEmpty ? [.paragraph(inlines: [])] : inner))
                continue
            }

            if isTableRow(trimmed), index + 1 < lines.count, isTableSeparator(lines[index + 1]) {
                let headers = splitTableRow(trimmed)
                index += 2
                var rows: [[String]] = []
                while index < lines.count, isTableRow(lines[index].trimmingCharacters(in: .whitespaces)) {
                    rows.append(splitTableRow(lines[index].trimmingCharacters(in: .whitespaces)))
                    index += 1
                }
                blocks.append(.table(headers: headers, rows: rows))
                continue
            }

            if let bullet = bulletPrefix(trimmed) {
                var items: [[DevMarkdownInline]] = []
                while index < lines.count {
                    let row = lines[index].trimmingCharacters(in: .whitespaces)
                    guard let prefix = bulletPrefix(row) else { break }
                    items.append(parseInline(String(row.dropFirst(prefix.count))))
                    index += 1
                }
                blocks.append(.unorderedList(items: items))
                continue
            }

            if let prefix = orderedPrefix(trimmed) {
                var items: [[DevMarkdownInline]] = []
                while index < lines.count {
                    let row = lines[index].trimmingCharacters(in: .whitespaces)
                    guard let p = orderedPrefix(row) else { break }
                    items.append(parseInline(String(row.dropFirst(p.count))))
                    index += 1
                }
                blocks.append(.orderedList(items: items))
                continue
            }

            var paragraphLines: [String] = []
            while index < lines.count {
                let row = lines[index]
                let t = row.trimmingCharacters(in: .whitespaces)
                if t.isEmpty { break }
                if t.hasPrefix("```") || isDivider(t) || headingLevel(t) != nil || t.hasPrefix(">")
                    || isTableRow(t) || bulletPrefix(t) != nil || orderedPrefix(t) != nil {
                    break
                }
                paragraphLines.append(row)
                index += 1
            }
            let joined = paragraphLines.joined(separator: " ")
            blocks.append(.paragraph(inlines: parseInline(joined)))
        }

        return blocks
    }

    static func parseInline(_ text: String) -> [DevMarkdownInline] {
        guard !text.isEmpty else { return [] }
        var spans: [DevMarkdownInline] = []
        var cursor = text.startIndex

        func appendPlain(until end: String.Index) {
            guard cursor < end else { return }
            let chunk = String(text[cursor..<end])
            if !chunk.isEmpty {
                spans.append(DevMarkdownInline(text: chunk, style: .plain))
            }
        }

        while cursor < text.endIndex {
            if text[cursor] == "`" {
                appendPlain(until: cursor)
                cursor = text.index(after: cursor)
                if let close = text[cursor...].firstIndex(of: "`") {
                    let code = String(text[cursor..<close])
                    spans.append(DevMarkdownInline(text: code, style: .code))
                    cursor = text.index(after: close)
                    continue
                }
                spans.append(DevMarkdownInline(text: "`", style: .plain))
                continue
            }

            if text[cursor] == "[" {
                if let closeBracket = text[cursor...].firstIndex(of: "]"),
                   closeBracket < text.endIndex,
                   text[text.index(after: closeBracket)] == "(",
                   let closeParen = text[text.index(after: closeBracket)...].firstIndex(of: ")") {
                    appendPlain(until: cursor)
                    let label = String(text[text.index(after: cursor)..<closeBracket])
                    let urlStart = text.index(closeBracket, offsetBy: 2)
                    let url = String(text[urlStart..<closeParen])
                    spans.append(DevMarkdownInline(text: label, style: .link(url: url)))
                    cursor = text.index(after: closeParen)
                    continue
                }
            }

            if text[cursor] == "*" {
                let next = text.index(after: cursor)
                if next < text.endIndex, text[next] == "*" {
                    appendPlain(until: cursor)
                    cursor = text.index(after: next)
                    if let close = text[cursor...].range(of: "**") {
                        let bold = String(text[cursor..<close.lowerBound])
                        spans.append(DevMarkdownInline(text: bold, style: .bold))
                        cursor = close.upperBound
                        continue
                    }
                    spans.append(DevMarkdownInline(text: "**", style: .plain))
                    continue
                }
                appendPlain(until: cursor)
                cursor = next
                if let close = text[cursor...].firstIndex(of: "*") {
                    let italic = String(text[cursor..<close])
                    spans.append(DevMarkdownInline(text: italic, style: .italic))
                    cursor = text.index(after: close)
                    continue
                }
                spans.append(DevMarkdownInline(text: "*", style: .plain))
                continue
            }

            if text[cursor] == "_" {
                appendPlain(until: cursor)
                cursor = text.index(after: cursor)
                if let close = text[cursor...].firstIndex(of: "_") {
                    let italic = String(text[cursor..<close])
                    spans.append(DevMarkdownInline(text: italic, style: .italic))
                    cursor = text.index(after: close)
                    continue
                }
                spans.append(DevMarkdownInline(text: "_", style: .plain))
                continue
            }

            cursor = text.index(after: cursor)
        }

        appendPlain(until: text.endIndex)
        return spans
    }

    private static func headingLevel(_ line: String) -> Int? {
        guard line.hasPrefix("#") else { return nil }
        var count = 0
        for ch in line {
            if ch == "#" { count += 1 } else { break }
        }
        guard (1...3).contains(count) else { return nil }
        guard line.count > count, line[line.index(line.startIndex, offsetBy: count)] == " " else { return nil }
        return count
    }

    private static func isDivider(_ line: String) -> Bool {
        let stripped = line.replacingOccurrences(of: " ", with: "")
        guard stripped.count >= 3 else { return false }
        let ch = stripped.first!
        return stripped.allSatisfy { $0 == ch } && (ch == "-" || ch == "*" || ch == "_")
    }

    private static func bulletPrefix(_ line: String) -> String? {
        for prefix in ["- ", "* ", "+ "] where line.hasPrefix(prefix) {
            return prefix
        }
        return nil
    }

    private static func orderedPrefix(_ line: String) -> String? {
        guard let dot = line.firstIndex(of: ".") else { return nil }
        let num = line[..<dot]
        guard !num.isEmpty, num.allSatisfy(\.isNumber), line.index(after: dot) < line.endIndex else { return nil }
        guard line[line.index(after: dot)] == " " else { return nil }
        return String(line[..<line.index(dot, offsetBy: 2)])
    }

    private static func isTableRow(_ line: String) -> Bool {
        line.contains("|")
    }

    private static func isTableSeparator(_ line: String) -> Bool {
        let cells = splitTableRow(line)
        guard !cells.isEmpty else { return false }
        return cells.allSatisfy { cell in
            let trimmed = cell.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty else { return false }
            return trimmed.allSatisfy { $0 == "-" || $0 == ":" }
        }
    }

    private static func splitTableRow(_ line: String) -> [String] {
        var raw = line.trimmingCharacters(in: .whitespaces)
        if raw.hasPrefix("|") { raw.removeFirst() }
        if raw.hasSuffix("|") { raw.removeLast() }
        return raw.split(separator: "|", omittingEmptySubsequences: false).map {
            String($0).trimmingCharacters(in: .whitespaces)
        }
    }
}
