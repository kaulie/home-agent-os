import Foundation

enum GameCommandType: String, CaseIterable {
    case start = "START"
    case pause = "PAUSE"
    case resume = "RESUME"
    case restart = "RESTART"
    case moveLeft = "MOVE_LEFT"
    case moveRight = "MOVE_RIGHT"
    case jump = "JUMP"
    case speedUp = "SPEED_UP"
    case speedDown = "SPEED_DOWN"
}

enum GameCommandSource: String {
    case voice = "VOICE"
    case gesture = "GESTURE"
    case system = "SYSTEM"
}

struct GameCommand: Equatable {
    let type: GameCommandType
    let source: GameCommandSource
    let timestampMs: Int64

    init(type: GameCommandType, source: GameCommandSource, timestampMs: Int64 = Int64(Date().timeIntervalSince1970 * 1000)) {
        self.type = type
        self.source = source
        self.timestampMs = timestampMs
    }

    var body: [String: Any] {
        [
            "type": type.rawValue,
            "source": source.rawValue,
            "timestamp": timestampMs,
        ]
    }
}

enum GameVoiceMapper {
    private static let rules: [(keys: [String], type: GameCommandType, priority: Int)] = [
        (["重新开始", "再来"], .restart, 10),
        (["开始游戏", "开始"], .start, 9),
        (["暂停"], .pause, 9),
        (["继续"], .resume, 9),
        (["快一点", "快点"], .speedUp, 8),
        (["慢一点", "慢点"], .speedDown, 8),
        (["向左", "左边", "左"], .moveLeft, 7),
        (["向右", "右边", "右"], .moveRight, 7),
        (["跳"], .jump, 7),
    ]

    static func match(_ transcript: String) -> GameCommandType? {
        let text = transcript
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "，", with: "")
            .replacingOccurrences(of: "。", with: "")
            .lowercased()
        guard !text.isEmpty else { return nil }
        var best: (GameCommandType, Int)?
        for rule in rules {
            for key in rule.keys {
                if text.contains(key) {
                    if best == nil || rule.priority > best!.1 {
                        best = (rule.type, rule.priority)
                    }
                }
            }
        }
        return best?.0
    }
}
