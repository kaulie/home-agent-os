import Foundation

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

    static func agent(handle: String) -> ChatMentionAgent? {
        fleetAssignees.first { $0.handle == handle }
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

    /// Active `@` token on the current line, if user is still typing a handle.
    static func activeQuery(in text: String) -> String? {
        let line = text.components(separatedBy: "\n").last ?? text
        let normalized = line.replacingOccurrences(of: "＠", with: "@")
        guard let atIndex = normalized.lastIndex(of: "@") else { return nil }

        if atIndex > normalized.startIndex {
            let before = normalized[normalized.index(before: atIndex)]
            if !before.isWhitespace {
                return nil
            }
        }

        let tail = String(normalized[normalized.index(after: atIndex)...])
        if tail.isEmpty {
            return ""
        }

        var query = ""
        for character in tail {
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

    private static func isTokenCharacter(_ character: Character) -> Bool {
        character.isLetter || character.isNumber || character.unicodeScalars.allSatisfy {
            tokenExtraScalars.contains($0)
        }
    }

    static func apply(handle: String, to text: inout String) {
        guard !handle.isEmpty else { return }
        let lines = text.components(separatedBy: "\n")
        guard !lines.isEmpty else {
            text = "@\(handle) "
            return
        }
        var last = lines[lines.count - 1]
        guard let atIndex = last.lastIndex(of: "@") else { return }
        last = String(last[..<atIndex]) + "@\(handle) "
        var rebuilt = lines
        rebuilt[rebuilt.count - 1] = last
        text = rebuilt.joined(separator: "\n")
    }
}
