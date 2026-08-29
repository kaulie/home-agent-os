import Foundation
import SwiftUI

/// In-chat project doc link: `[[doc:docs/agent-coordination.md]]`
enum ChatDocReference {
    private static let pattern =
        #"\[\[doc:([^\]\n]+)\]\]"#

    static func token(path: String) -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        return "[[doc:\(trimmed)]]"
    }

    static func label(path: String) -> String {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        return (trimmed as NSString).lastPathComponent
    }

    static func docURL(path: String) -> URL? {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        var components = URLComponents()
        components.scheme = "hadev-doc"
        components.host = "open"
        components.queryItems = [URLQueryItem(name: "path", value: trimmed)]
        return components.url
    }

    static func path(from url: URL) -> String? {
        guard url.scheme == "hadev-doc" else { return nil }
        if let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
           let value = items.first(where: { $0.name == "path" })?.value,
           !value.isEmpty {
            return value
        }
        let raw = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return raw.isEmpty ? nil : raw
    }

    static func attributedBody(
        _ raw: String,
        textColor: Color,
        linkColor: Color
    ) -> AttributedString {
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            var plain = AttributedString(raw)
            plain.foregroundColor = textColor
            return plain
        }
        let ns = raw as NSString
        let matches = regex.matches(in: raw, range: NSRange(location: 0, length: ns.length))
        guard !matches.isEmpty else {
            var plain = AttributedString(raw)
            plain.foregroundColor = textColor
            return plain
        }

        var result = AttributedString()
        var cursor = 0
        for match in matches {
            let range = match.range
            if range.location > cursor {
                var chunk = AttributedString(ns.substring(with: NSRange(location: cursor, length: range.location - cursor)))
                chunk.foregroundColor = textColor
                result.append(chunk)
            }
            let pathRange = match.range(at: 1)
            let path = ns.substring(with: pathRange)
            let label = "📄 \(label(path: path))"
            var link = AttributedString(label)
            link.foregroundColor = linkColor
            link.underlineStyle = .single
            if let url = docURL(path: path) {
                link.link = url
            }
            result.append(link)
            cursor = range.location + range.length
        }
        if cursor < ns.length {
            var tail = AttributedString(ns.substring(from: cursor))
            tail.foregroundColor = textColor
            result.append(tail)
        }
        return result
    }
}

enum ChatDocAutocomplete {
    private static let opener = "[["

    /// Text after `[[` on the current line when the bracket pair is not closed yet.
    static func activeQuery(in text: String) -> String? {
        let line = text.components(separatedBy: "\n").last ?? text
        guard let start = line.range(of: opener, options: .backwards) else { return nil }
        let tail = String(line[start.upperBound...])
        if tail.contains("]]") { return nil }
        return tail
    }

    static func apply(path: String, to text: inout String) {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let token = ChatDocReference.token(path: trimmed)
        let lines = text.components(separatedBy: "\n")
        guard !lines.isEmpty else {
            text = token + " "
            return
        }
        var last = lines[lines.count - 1]
        guard let start = last.range(of: opener, options: .backwards) else { return }
        last = String(last[..<start.lowerBound]) + token + " "
        var rebuilt = lines
        rebuilt[rebuilt.count - 1] = last
        text = rebuilt.joined(separator: "\n")
    }
}
