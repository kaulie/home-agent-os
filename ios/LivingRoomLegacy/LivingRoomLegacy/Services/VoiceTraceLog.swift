import Foundation

struct VoiceTraceLine {
    enum Kind: String {
        case status = "状态"
        case partial = "片段"
        case final = "最终"
        case send = "发送"
        case error = "错误"
    }

    let id: String
    let at: TimeInterval
    let kind: Kind
    let text: String

    init(kind: Kind, text: String) {
        id = UUID().uuidString
        at = Date().timeIntervalSince1970
        self.kind = kind
        self.text = text
    }
}

enum VoiceTraceLog {
    private static var memory: [VoiceTraceLine] = []
    private static let maxCount = 48

    static func append(kind: VoiceTraceLine.Kind, text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if kind == .partial, memory.first?.kind == .partial {
            let prev = memory[0]
            memory[0] = VoiceTraceLine(kind: .partial, text: trimmed)
            _ = prev
        } else {
            memory.insert(VoiceTraceLine(kind: kind, text: trimmed), at: 0)
        }
        if memory.count > maxCount {
            memory = Array(memory.prefix(maxCount))
        }
    }

    static func recent(_ count: Int = 20) -> [VoiceTraceLine] {
        Array(memory.prefix(max(1, count)))
    }

    static func clear() {
        memory = []
    }

    static func formattedText(for lines: [VoiceTraceLine]) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return lines.map { line in
            let t = formatter.string(from: Date(timeIntervalSince1970: line.at))
            return "\(t) [\(line.kind.rawValue)] \(line.text)"
        }.joined(separator: "\n")
    }
}
