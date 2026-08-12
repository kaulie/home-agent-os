import Foundation

/// Synced Brain wall clock for timingDue / miss-window (not raw local wall clock).
enum BrainTimeSync {
    private static let lock = NSLock()
    private static var brainTimeMs: Int64?
    private static var localMonoAtSync: TimeInterval?

    static func applyHeartbeat(brainTimeMs value: Int64?) {
        guard let value, value > 0 else { return }
        lock.lock()
        defer { lock.unlock() }
        brainTimeMs = value
        localMonoAtSync = ProcessInfo.processInfo.systemUptime
    }

    static func nowMs() -> Int64 {
        lock.lock()
        defer { lock.unlock() }
        guard let brain = brainTimeMs, let mono = localMonoAtSync else {
            return Int64(Date().timeIntervalSince1970 * 1000)
        }
        let elapsed = ProcessInfo.processInfo.systemUptime - mono
        return brain + Int64(elapsed * 1000)
    }
}

enum TimingBeats {
    private static let lock = NSLock()
    private static var beats: [String: Int] = [:]

    private static func key(_ intentId: String, _ step: Int) -> String {
        "\(intentId)|\(step)"
    }

    static func get(intentId: String, step: Int) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return beats[key(intentId, step)] ?? 0
    }

    static func set(intentId: String, step: Int, beat: Int) {
        lock.lock()
        defer { lock.unlock() }
        beats[key(intentId, step)] = max(0, beat)
    }

    @discardableResult
    static func advance(intentId: String, step: Int) -> Int {
        lock.lock()
        defer { lock.unlock() }
        let k = key(intentId, step)
        let nxt = (beats[k] ?? 0) + 1
        beats[k] = nxt
        return nxt
    }
}

struct ExecutionTiming: Equatable {
    static let oneShotMissMs: Int64 = 15 * 60 * 1000
    static let periodicMissCapMs: Int64 = 15 * 60 * 1000

    enum Mode: String {
        case immediate, delay, interval, cron
    }

    var mode: Mode
    var execTime: Int64?
    var firstExecTime: Int64?
    var intervalSec: Int?
    var cron: String?
    var timezone: String?
    var endTime: Int64?
    var count: Int?

    var isRecurring: Bool { mode == .interval || mode == .cron }

    static func parse(from step: [String: Any]) -> ExecutionTiming {
        guard let raw = step["execution_timing"] as? [String: Any] else {
            return ExecutionTiming(mode: .immediate)
        }
        let modeStr = (raw["mode"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            ?? "immediate"
        let mode = Mode(rawValue: modeStr) ?? .immediate
        return ExecutionTiming(
            mode: mode,
            execTime: asMs(raw["exec_time"]),
            firstExecTime: asMs(raw["first_exec_time"]),
            intervalSec: intPositive(raw["interval_sec"]),
            cron: (raw["cron"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty,
            timezone: (raw["timezone"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty,
            endTime: asMs(raw["end_time"]),
            count: intPositive(raw["count"])
        )
    }

    private static func asMs(_ value: Any?) -> Int64? {
        guard let value else { return nil }
        var n: Int64?
        if let i = value as? Int64 { n = i }
        else if let i = value as? Int { n = Int64(i) }
        else if let d = value as? Double { n = Int64(d) }
        else if let s = value as? String, let i = Int64(s) { n = i }
        guard var ms = n, ms > 0 else { return nil }
        if ms < 10_000_000_000 { ms *= 1000 }
        return ms
    }

    private static func intPositive(_ value: Any?) -> Int? {
        let n: Int?
        if let i = value as? Int { n = i }
        else if let i = value as? Int64 { n = Int(i) }
        else if let s = value as? String { n = Int(s) }
        else { n = nil }
        guard let v = n, v > 0 else { return nil }
        return v
    }

    func plannedStartMs(beatIndex: Int) -> Int64? {
        guard beatIndex >= 0 else { return nil }
        switch mode {
        case .immediate:
            return nil
        case .delay:
            return execTime
        case .interval:
            guard let first = firstExecTime, let sec = intervalSec else { return nil }
            return first + Int64(beatIndex) * Int64(sec) * 1000
        case .cron:
            guard let first = firstExecTime else { return nil }
            if beatIndex == 0 { return first }
            var t = first
            for _ in 0 ..< beatIndex {
                guard let nxt = Self.cronNextAfter(cron ?? "", afterMs: t, tzName: timezone) else {
                    return nil
                }
                t = nxt
            }
            return t
        }
    }

    func nextPlannedAfter(_ plannedStart: Int64) -> Int64? {
        switch mode {
        case .interval:
            guard let sec = intervalSec else { return nil }
            return plannedStart + Int64(sec) * 1000
        case .cron:
            return Self.cronNextAfter(cron ?? "", afterMs: plannedStart, tzName: timezone)
        default:
            return nil
        }
    }

    func missWindowMs(plannedStart: Int64) -> Int64 {
        if !isRecurring { return Self.oneShotMissMs }
        guard let nxt = nextPlannedAfter(plannedStart), nxt > plannedStart else {
            return Self.periodicMissCapMs
        }
        let half = max(Int64(0), (nxt - plannedStart) / 2)
        return min(half, Self.periodicMissCapMs)
    }

    struct Gate {
        var due: Bool
        var skipBeat: Bool
        var terminal: Bool
        var reason: String
        var plannedStart: Int64?
    }

    func gate(nowMs: Int64, beatIndex: Int = 0) -> Gate {
        if mode == .immediate {
            return Gate(due: true, skipBeat: false, terminal: false, reason: "immediate", plannedStart: nil)
        }
        if let count, beatIndex >= count {
            return Gate(due: false, skipBeat: false, terminal: true, reason: "count exhausted", plannedStart: nil)
        }
        guard let planned = plannedStartMs(beatIndex: beatIndex) else {
            return Gate(due: false, skipBeat: false, terminal: false, reason: "missing planned start", plannedStart: nil)
        }
        if let endTime, planned > endTime {
            return Gate(due: false, skipBeat: false, terminal: true, reason: "past end_time", plannedStart: planned)
        }
        if nowMs < planned {
            return Gate(due: false, skipBeat: false, terminal: false, reason: "wait until \(planned)", plannedStart: planned)
        }
        let late = nowMs - planned
        let window = missWindowMs(plannedStart: planned)
        if late > window {
            if isRecurring {
                return Gate(
                    due: false,
                    skipBeat: true,
                    terminal: false,
                    reason: "miss window exceeded (\(late)>\(window))",
                    plannedStart: planned
                )
            }
            return Gate(
                due: false,
                skipBeat: false,
                terminal: true,
                reason: "one-shot expired (\(late)>\(window))",
                plannedStart: planned
            )
        }
        return Gate(due: true, skipBeat: false, terminal: false, reason: "due", plannedStart: planned)
    }

    /// Minimal 5-field cron next (min hour dom mon dow), timezone name or UTC.
    static func cronNextAfter(_ expr: String, afterMs: Int64, tzName: String?) -> Int64? {
        let parts = expr.trimmingCharacters(in: .whitespacesAndNewlines).split(whereSeparator: { $0.isWhitespace }).map(String.init)
        guard parts.count == 5 else { return nil }
        guard let minutes = parseCronField(parts[0], minV: 0, maxV: 59)?.sorted(),
              let hours = parseCronField(parts[1], minV: 0, maxV: 23)?.sorted(),
              let doms = parseCronField(parts[2], minV: 1, maxV: 31),
              let months = parseCronField(parts[3], minV: 1, maxV: 12),
              let dows = parseCronField(parts[4], minV: 0, maxV: 6)
        else { return nil }

        var cal = Calendar(identifier: .gregorian)
        if let tzName, let tz = TimeZone(identifier: tzName) {
            cal.timeZone = tz
        } else {
            cal.timeZone = TimeZone(secondsFromGMT: 0) ?? .gmt
        }
        let after = Date(timeIntervalSince1970: TimeInterval(afterMs) / 1000.0)
        guard var start = cal.date(byAdding: .minute, value: 1, to: after) else { return nil }
        start = cal.date(bySetting: .second, value: 0, of: start) ?? start
        start = cal.date(bySetting: .nanosecond, value: 0, of: start) ?? start

        let domStar = parts[2] == "*" || parts[2].hasPrefix("*/")
        let dowStar = parts[4] == "*" || parts[4].hasPrefix("*/")

        var day = cal.startOfDay(for: start)
        for _ in 0 ..< 400 {
            let month = cal.component(.month, from: day)
            if months.contains(month) {
                let weekday = cal.component(.weekday, from: day) // 1=Sun..7=Sat
                let cronWd = weekday - 1
                let dom = cal.component(.day, from: day)
                let dayOk: Bool
                if domStar && dowStar { dayOk = true }
                else if domStar { dayOk = dows.contains(cronWd) }
                else if dowStar { dayOk = doms.contains(dom) }
                else { dayOk = doms.contains(dom) || dows.contains(cronWd) }
                if dayOk {
                    for hour in hours {
                        for minute in minutes {
                            var comps = cal.dateComponents([.year, .month, .day], from: day)
                            comps.hour = hour
                            comps.minute = minute
                            comps.second = 0
                            if let cand = cal.date(from: comps), cand >= start {
                                return Int64(cand.timeIntervalSince1970 * 1000)
                            }
                        }
                    }
                }
            }
            guard let next = cal.date(byAdding: .day, value: 1, to: day) else { break }
            day = next
        }
        return nil
    }

    private static func parseCronField(_ field: String, minV: Int, maxV: Int) -> Set<Int>? {
        let trimmed = field.trimmingCharacters(in: .whitespacesAndNewlines)
        let stepParts = trimmed.split(separator: "/", maxSplits: 1).map(String.init)
        let base = stepParts[0]
        let step = stepParts.count > 1 ? (Int(stepParts[1]) ?? 1) : 1
        guard step > 0 else { return nil }
        var values = Set<Int>()
        if base == "*" {
            values = Set(minV ... maxV)
        } else {
            for part in base.split(separator: ",") {
                let p = String(part)
                if p.contains("-") {
                    let ab = p.split(separator: "-", maxSplits: 1)
                    guard ab.count == 2, let a = Int(ab[0]), let b = Int(ab[1]) else { return nil }
                    values.formUnion(a ... b)
                } else if let v = Int(p) {
                    values.insert(v)
                } else {
                    return nil
                }
            }
        }
        if base == "*" {
            return Set(values.filter { ($0 - minV) % step == 0 && $0 >= minV && $0 <= maxV })
        }
        guard let start = values.sorted().first else { return [] }
        return Set(values.filter { $0 >= minV && $0 <= maxV && ($0 - start) % step == 0 })
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
