import Foundation

enum WireTime {
    static func decode<K: CodingKey>(_ c: KeyedDecodingContainer<K>, key: K) -> Date? {
        if let value = try? c.decode(Double.self, forKey: key) {
            if value > 10_000_000_000 {
                return Date(timeIntervalSince1970: value / 1000)
            }
            return Date(timeIntervalSince1970: value)
        }
        if let value = try? c.decode(Int.self, forKey: key) {
            let d = TimeInterval(value)
            if d > 10_000_000_000 {
                return Date(timeIntervalSince1970: d / 1000)
            }
            return Date(timeIntervalSince1970: d)
        }
        if let value = try? c.decode(String.self, forKey: key), let d = Double(value) {
            if d > 10_000_000_000 {
                return Date(timeIntervalSince1970: d / 1000)
            }
            return Date(timeIntervalSince1970: d)
        }
        return nil
    }

    static func parseAny(_ value: Any?) -> Date? {
        switch value {
        case let value as Double:
            if value > 10_000_000_000 {
                return Date(timeIntervalSince1970: value / 1000)
            }
            return Date(timeIntervalSince1970: value)
        case let value as Int:
            let d = TimeInterval(value)
            if d > 10_000_000_000 {
                return Date(timeIntervalSince1970: d / 1000)
            }
            return Date(timeIntervalSince1970: d)
        case let value as String:
            guard let d = Double(value) else { return nil }
            if d > 10_000_000_000 {
                return Date(timeIntervalSince1970: d / 1000)
            }
            return Date(timeIntervalSince1970: d)
        default:
            return nil
        }
    }

    static func absoluteLabel(_ date: Date) -> String {
        formatter.string(from: date)
    }

    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f
    }()
}

enum DevRelativeTime {
    static func label(since date: Date, now: Date = Date()) -> String {
        let seconds = max(0, Int(now.timeIntervalSince(date)))
        if seconds < 10 { return "刚刚" }
        if seconds < 60 { return "\(seconds) 秒前" }
        let minutes = seconds / 60
        if minutes < 60 { return "\(minutes) 分钟前" }
        let hours = minutes / 60
        if hours < 24 { return "\(hours) 小时前" }
        let days = hours / 24
        return "\(days) 天前"
    }
}
