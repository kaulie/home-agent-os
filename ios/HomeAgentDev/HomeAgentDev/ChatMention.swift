import Foundation
import SwiftUI

struct ChatMentionAgent: Identifiable, Equatable {
    var id: String { handle }

    let handle: String
    let displayName: String

    var mentionToken: String { "@\(handle)" }

    var pickerLabel: String {
        "\(mentionToken) · \(displayName)"
    }
}

enum ChatMentionCatalog {
    static let agents: [ChatMentionAgent] = [
        ChatMentionAgent(handle: "all", displayName: "所有人"),
        ChatMentionAgent(handle: "coordinator", displayName: "system coordinator agent"),
        ChatMentionAgent(handle: "controller", displayName: "dev controller agent"),
        ChatMentionAgent(handle: "brain", displayName: "brain agent"),
        ChatMentionAgent(handle: "runtime", displayName: "runtime dev agent"),
        ChatMentionAgent(handle: "ui", displayName: "UI dev agent"),
        ChatMentionAgent(handle: "capability", displayName: "capability dev agent"),
        ChatMentionAgent(handle: "quality", displayName: "quality agent"),
        ChatMentionAgent(handle: "deploy", displayName: "deploy agent"),
        ChatMentionAgent(handle: "sre", displayName: "sre agent"),
        ChatMentionAgent(handle: "dba", displayName: "dba agent"),
    ]

    static var fleetAssignees: [ChatMentionAgent] {
        agents.filter { $0.handle != "all" }
    }

    static let knownHandles: Set<String> = Set(agents.map(\.handle))

    static func agent(handle: String) -> ChatMentionAgent? {
        agents.first { $0.handle == handle }
    }

    static func filtered(query: String) -> [ChatMentionAgent] {
        let key = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if key.isEmpty {
            return agents
        }
        return agents.filter { agent in
            agent.handle.lowercased().hasPrefix(key)
                || agent.displayName.lowercased().contains(key)
        }
    }
}

enum ChatMentionAutocomplete {
    private static let tokenExtraScalars = CharacterSet(charactersIn: "_-")

    /// Active `@` token being typed (not only at line start).
    /// Trigger when `@` is at start / after whitespace / after non-handle characters
    /// (so `你好@brain` works; `user@email` does not).
    static func activeQuery(in text: String) -> String? {
        let normalized = text.replacingOccurrences(of: "＠", with: "@")
        guard let atIndex = activeAtIndex(in: normalized) else { return nil }

        let afterAt = normalized.index(after: atIndex)
        let tail = String(normalized[afterAt...])
        // Only consider the remainder of the current line.
        let lineTail = tail.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false).first
            .map(String.init) ?? tail

        if lineTail.isEmpty {
            return ""
        }

        var query = ""
        for character in lineTail {
            if isTokenCharacter(character) {
                query.append(character)
                continue
            }
            if character.isWhitespace {
                // iOS may auto-insert a space right after "@"; keep the picker open.
                if query.isEmpty {
                    continue
                }
                return nil
            }
            return nil
        }
        return query
    }

    /// Index of the `@` that is currently being composed, if any.
    static func activeAtIndex(in text: String) -> String.Index? {
        let normalized = text.replacingOccurrences(of: "＠", with: "@")
        var searchEnd = normalized.endIndex
        while searchEnd > normalized.startIndex {
            let slice = normalized[..<searchEnd]
            guard let atIndex = slice.lastIndex(of: "@") else { return nil }

            let validStart: Bool
            if atIndex == normalized.startIndex {
                validStart = true
            } else {
                let before = normalized[normalized.index(before: atIndex)]
                // Allow after whitespace OR non-handle chars (CJK, punctuation).
                // Block when glued to a Latin handle/email local-part.
                validStart = before.isWhitespace || !isTokenCharacter(before)
            }

            if validStart {
                let afterAt = normalized.index(after: atIndex)
                let lineTail = String(normalized[afterAt...])
                    .split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false)
                    .first
                    .map(String.init) ?? ""
                if isIncompleteMentionTail(lineTail) {
                    return atIndex
                }
            }
            searchEnd = atIndex
        }
        return nil
    }

    /// Tail after `@` still looks like an in-progress handle (not a finished mention).
    private static func isIncompleteMentionTail(_ tail: String) -> Bool {
        if tail.isEmpty { return true }
        var query = ""
        for character in tail {
            if isTokenCharacter(character) {
                query.append(character)
                continue
            }
            if character.isWhitespace {
                return query.isEmpty
            }
            return false
        }
        return true
    }

    private static func isTokenCharacter(_ character: Character) -> Bool {
        character.isLetter || character.isNumber || character.unicodeScalars.allSatisfy {
            tokenExtraScalars.contains($0)
        }
    }

    static func apply(handle: String, to text: inout String) {
        guard !handle.isEmpty else { return }
        let normalized = text.replacingOccurrences(of: "＠", with: "@")
        guard let atIndex = activeAtIndex(in: normalized) else {
            text = normalized.isEmpty ? "@\(handle) " : normalized + "@\(handle) "
            return
        }
        let prefix = String(normalized[..<atIndex])
        let afterAt = normalized.index(after: atIndex)
        let rest = String(normalized[afterAt...])
        var dropCount = 0
        for character in rest {
            if isTokenCharacter(character) {
                dropCount += 1
                continue
            }
            // Skip a single auto-inserted space right after "@".
            if character.isWhitespace, dropCount == 0 {
                dropCount += 1
                continue
            }
            break
        }
        let remainder = String(rest.dropFirst(dropCount))
        text = prefix + "@\(handle) " + remainder
    }
}

enum ChatMentionHighlight {
    private static let pattern = #"@([A-Za-z][A-Za-z0-9_-]*)"#

    /// Style known `@handle` tokens inside a plain string.
    static func appendHighlighted(
        _ raw: String,
        to result: inout AttributedString,
        textColor: Color,
        mentionColor: Color
    ) {
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            var plain = AttributedString(raw)
            plain.foregroundColor = textColor
            result.append(plain)
            return
        }
        let ns = raw as NSString
        let matches = regex.matches(in: raw, range: NSRange(location: 0, length: ns.length))
        guard !matches.isEmpty else {
            var plain = AttributedString(raw)
            plain.foregroundColor = textColor
            result.append(plain)
            return
        }

        var cursor = 0
        for match in matches {
            let full = match.range
            let handleRange = match.range(at: 1)
            let handle = ns.substring(with: handleRange)
            let isKnown = ChatMentionCatalog.knownHandles.contains(handle)

            if full.location > cursor {
                var chunk = AttributedString(
                    ns.substring(with: NSRange(location: cursor, length: full.location - cursor))
                )
                chunk.foregroundColor = textColor
                result.append(chunk)
            }

            var token = AttributedString(ns.substring(with: full))
            if isKnown {
                token.foregroundColor = mentionColor
                token.font = .system(size: 15, weight: .semibold, design: .rounded)
                token.backgroundColor = mentionColor.opacity(0.18)
            } else {
                token.foregroundColor = textColor
            }
            result.append(token)
            cursor = full.location + full.length
        }
        if cursor < ns.length {
            var tail = AttributedString(ns.substring(from: cursor))
            tail.foregroundColor = textColor
            result.append(tail)
        }
    }
}
