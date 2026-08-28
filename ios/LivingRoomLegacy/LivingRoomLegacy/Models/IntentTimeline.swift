import Foundation
import UIKit

enum TimelineStepState {
    case pending
    case active
    case done
    case failed
}

struct TimelineStep {
    let wireStatus: String
    let label: String
    let state: TimelineStepState
}

struct IntentTimeline {
    var intentId: String
    var currentWireStatus: String
    var steps: [TimelineStep]
    var bannerText: String

    private static let phaseDefs: [(wire: String, label: String)] = [
        ("sending", "正在发送"),
        ("intent_received", "已到达服务器"),
        ("intent_parsed", "意图解析"),
        ("intent_scheduled", "任务调度"),
        ("intent_dispatched", "分发到节点"),
        ("running", "执行中"),
        ("succeeded", "完成（成功）"),
    ]

    static func posting() -> IntentTimeline {
        build(
            intentId: "",
            currentWire: "sending",
            reachedWires: [],
            failed: false,
            banner: "正在发送请求…"
        )
    }

    static func sendFailed(_ message: String) -> IntentTimeline {
        var steps = phaseDefs.map { def -> TimelineStep in
            if def.wire == "sending" {
                return TimelineStep(wireStatus: def.wire, label: def.label, state: .failed)
            }
            return TimelineStep(wireStatus: def.wire, label: def.label, state: .pending)
        }
        return IntentTimeline(
            intentId: "",
            currentWireStatus: "failed",
            steps: steps,
            bannerText: message.isEmpty ? "发送失败" : message
        )
    }

    static func fromSnapshot(_ snap: IntentDetailSnapshot) -> IntentTimeline {
        let wires = Set(snap.statusLog.map { $0.status.lowercased() })
        var reached = Array(wires)
        if !snap.status.isEmpty {
            reached.append(snap.status.lowercased())
        }
        let current = snap.status.isEmpty ? (snap.statusLog.last?.status ?? "intent_received") : snap.status
        let failed = isFailedStatus(current)
        let banner: String
        if failed {
            banner = snap.errorMessage.isEmpty ? "任务失败" : snap.errorMessage
        } else if isTerminalStatus(current) {
            banner = "任务完成"
        } else if !snap.intentId.isEmpty {
            banner = "intent #\(snap.intentId) · \(current)"
        } else {
            banner = current
        }
        return build(
            intentId: snap.intentId,
            currentWire: failed ? "failed" : current,
            reachedWires: reached,
            failed: failed,
            banner: banner
        )
    }

    private static func build(
        intentId: String,
        currentWire: String,
        reachedWires: [String],
        failed: Bool,
        banner: String
    ) -> IntentTimeline {
        let reached = Set(reachedWires.map { $0.lowercased() })
        let current = currentWire.lowercased()
        let currentRank = rank(for: current, failed: failed)

        let steps = phaseDefs.map { def -> TimelineStep in
            if def.wire == "succeeded" {
                if failed {
                    return TimelineStep(wireStatus: def.wire, label: "完成（失败）", state: .failed)
                }
                if reached.contains("succeeded") || current == "succeeded" {
                    return TimelineStep(wireStatus: def.wire, label: def.label, state: .done)
                }
                if currentRank >= rank(for: "running", failed: false) && !failed {
                    return TimelineStep(wireStatus: def.wire, label: def.label, state: .active)
                }
                return TimelineStep(wireStatus: def.wire, label: def.label, state: .pending)
            }

            let r = rank(for: def.wire, failed: false)
            let state: TimelineStepState
            if failed && def.wire == current {
                state = .failed
            } else if reached.contains(def.wire) || (r < currentRank && current != "sending") {
                state = .done
            } else if def.wire == current || (def.wire == "intent_parsed" && current == "intent_received" && reached.contains("intent_received")) {
                state = .active
            } else if r == currentRank {
                state = .active
            } else {
                state = .pending
            }
            return TimelineStep(wireStatus: def.wire, label: def.label, state: state)
        }

        return IntentTimeline(
            intentId: intentId,
            currentWireStatus: currentWire,
            steps: steps,
            bannerText: banner
        )
    }

    private static func rank(for wire: String, failed: Bool) -> Int {
        let w = wire.lowercased()
        if w == "sending" { return 0 }
        if w == "intent_received" { return 1 }
        if w == "intent_parsed" { return 2 }
        if w == "intent_scheduled" { return 3 }
        if w == "intent_dispatched" { return 4 }
        if w == "running" { return 5 }
        if w == "succeeded" || w == "failed" || failed { return 6 }
        return 1
    }

    private static func isTerminalStatus(_ status: String) -> Bool {
        let s = status.lowercased()
        return s == "succeeded" || s == "failed" || s == "error" || s == "cancelled"
    }

    private static func isFailedStatus(_ status: String) -> Bool {
        let s = status.lowercased()
        return s == "failed" || s == "error" || s == "cancelled"
    }
}

struct SimpleProgressStep {
    let label: String
    let state: TimelineStepState
}

extension IntentTimeline {
    /// 儿童向：4 步进度文案
    var simpleBanner: String {
        let w = currentWireStatus.lowercased()
        if w == "sending" { return "正在发出…" }
        if IntentTimeline.isFailedStatus(w) {
            return bannerText.isEmpty ? "没成功" : bannerText
        }
        if w == "succeeded" { return "做好了 ✓" }
        if w == "intent_received" || w == "intent_parsed" { return "服务器收到了" }
        if w == "intent_scheduled" || w == "intent_dispatched" || w == "running" {
            return "正在帮你做…"
        }
        if !intentId.isEmpty { return "已发出，等待回复…" }
        return "处理中…"
    }

    var simpleSteps: [SimpleProgressStep] {
        let failed = IntentTimeline.isFailedStatus(currentWireStatus.lowercased())
        let rank = simplePhaseRank(for: currentWireStatus)
        let lastLabel = failed ? "失败了" : "好了"
        let labels = ["发出", "收到了", "正在做", lastLabel]
        return labels.enumerated().map { index, label in
            let state: TimelineStepState
            if failed {
                if index < rank {
                    state = .done
                } else if index == rank {
                    state = .failed
                } else {
                    state = .pending
                }
            } else if index < rank {
                state = .done
            } else if index == rank && rank < 3 {
                state = .active
            } else if index == 3 && currentWireStatus.lowercased() == "succeeded" {
                state = .done
            } else if index == rank {
                state = .active
            } else {
                state = .pending
            }
            return SimpleProgressStep(label: label, state: state)
        }
    }

    private func simplePhaseRank(for wire: String) -> Int {
        switch wire.lowercased() {
        case "sending":
            return 0
        case "intent_received", "intent_parsed":
            return 1
        case "intent_scheduled", "intent_dispatched", "running":
            return 2
        case "succeeded", "failed", "error", "cancelled":
            return intentId.isEmpty ? 0 : 3
        default:
            return intentId.isEmpty ? 0 : 1
        }
    }
}
