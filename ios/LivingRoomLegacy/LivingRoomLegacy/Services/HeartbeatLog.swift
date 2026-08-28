import Foundation

struct HeartbeatRecord: Codable {
    let at: TimeInterval
    let ok: Bool
    let detail: String
}

enum HeartbeatLog {
    private static let key = "legacy.heartbeatLog"
    private static let maxCount = 12

    static func append(ok: Bool, detail: String = "") {
        var items = load()
        let entry = HeartbeatRecord(at: Date().timeIntervalSince1970, ok: ok, detail: detail)
        items.insert(entry, at: 0)
        if items.count > maxCount {
            items = Array(items.prefix(maxCount))
        }
        save(items)
        if ok {
            ParticipantStore.lastHeartbeatAt = entry.at
        }
    }

    static func recent(_ count: Int = 5) -> [HeartbeatRecord] {
        Array(load().prefix(max(1, count)))
    }

    static func formattedLines(for records: [HeartbeatRecord]) -> [String] {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return records.map { record in
            let time = formatter.string(from: Date(timeIntervalSince1970: record.at))
            let mark = record.ok ? "OK" : "FAIL"
            if record.detail.isEmpty {
                return "\(time)  \(mark)"
            }
            return "\(time)  \(mark)  ·  \(record.detail)"
        }
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: key)
        ParticipantStore.lastHeartbeatAt = 0
    }

    private static func load() -> [HeartbeatRecord] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let items = try? JSONDecoder().decode([HeartbeatRecord].self, from: data) else {
            return []
        }
        return items
    }

    private static func save(_ items: [HeartbeatRecord]) {
        guard let data = try? JSONEncoder().encode(items) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }
}

struct HeartbeatResult {
    let ok: Bool
    let detail: String
}
