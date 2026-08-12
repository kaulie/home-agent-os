import Foundation

/// Parsed subset of GoPro `/gp/gpControl/status` (HERO4+ gpControl).
struct GoProStatusSnapshot: Equatable {
    enum Mode: Int, Equatable {
        case video = 0
        case photo = 1
        case multiShot = 2
        case unknown = -1

        var label: String {
            switch self {
            case .video: return "录像"
            case .photo: return "拍照"
            case .multiShot: return "连拍/延时"
            case .unknown: return "未知模式"
            }
        }
    }

    let mode: Mode
    let subMode: Int
    let subModeLabel: String
    /// status["8"]: recording / processing
    let isBusy: Bool
    /// Elapsed seconds while recording (status["13"])
    let recordElapsedSec: Int
    let batteryPercent: Int?
    let camName: String?
    let photosTaken: Int?
    let photosRemaining: Int?
    let videosTaken: Int?
    let sdInserted: Bool?

    /// One-line for header `GoPro当前状态`.
    var displayLine: String {
        var parts: [String] = ["\(mode.label)/\(subModeLabel)"]
        if isBusy {
            parts.append("忙碌/录制中 \(Self.formatDuration(recordElapsedSec))")
        } else {
            parts.append("空闲")
        }
        if let batteryPercent {
            parts.append("电量\(batteryPercent)%")
        }
        if let camName, !camName.isEmpty {
            parts.append(camName)
        }
        return parts.joined(separator: " · ")
    }

    /// Multi-line for「接口返回」.
    var displayText: String {
        var lines: [String] = []
        lines.append("模式：\(mode.label)（status.43=\(mode == .unknown ? "?" : "\(mode.rawValue)")）")
        lines.append("子模式：\(subModeLabel)（status.44=\(subMode)）")
        lines.append("忙碌/录制：\(isBusy ? "是" : "否")（status.8）")
        if isBusy || recordElapsedSec > 0 {
            lines.append("已计时：\(Self.formatDuration(recordElapsedSec))（status.13=\(recordElapsedSec)s）")
        }
        if let batteryPercent {
            lines.append("电量：\(batteryPercent)%（status.70）")
        }
        if let photosTaken {
            lines.append("已拍张数：\(photosTaken)（status.38）")
        }
        if let photosRemaining {
            lines.append("剩余可拍：\(photosRemaining)（status.34）")
        }
        if let videosTaken {
            lines.append("已录段数：\(videosTaken)（status.39）")
        }
        if let sdInserted {
            lines.append("SD 卡：\(sdInserted ? "已插入" : "未插入")（status.33）")
        }
        if let camName, !camName.isEmpty {
            lines.append("相机名：\(camName)（status.30）")
        }
        if mode == .video, isBusy {
            lines.append("提示：当前在录像/延时计时，不是拍照页；拍照前需切到拍照模式并停止录制。")
        }
        if mode == .multiShot {
            lines.append("提示：连拍/延时模式屏幕上常有计时器；单张拍照请切到「拍照」模式。")
        }
        return lines.joined(separator: "\n")
    }

    static func parse(jsonBody: String) -> GoProStatusSnapshot? {
        guard let data = jsonBody.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let status = root["status"] as? [String: Any] else {
            return nil
        }
        return parse(statusObject: status)
    }

    static func parse(statusObject status: [String: Any]) -> GoProStatusSnapshot {
        let modeRaw = intValue(status["43"]) ?? -1
        let mode = Mode(rawValue: modeRaw) ?? .unknown
        let sub = intValue(status["44"]) ?? 0
        let busy = (intValue(status["8"]) ?? 0) != 0
        let elapsed = intValue(status["13"]) ?? 0
        return GoProStatusSnapshot(
            mode: mode,
            subMode: sub,
            subModeLabel: subModeLabel(mode: mode, sub: sub),
            isBusy: busy,
            recordElapsedSec: elapsed,
            batteryPercent: intValue(status["70"]),
            camName: status["30"] as? String,
            photosTaken: intValue(status["38"]),
            photosRemaining: intValue(status["34"]),
            videosTaken: intValue(status["39"]),
            sdInserted: intValue(status["33"]).map { $0 != 0 }
        )
    }

    private static func subModeLabel(mode: Mode, sub: Int) -> String {
        switch mode {
        case .video:
            switch sub {
            case 0: return "普通录像"
            case 1: return "延时录像(TimeLapse)"
            case 2: return "录像+拍照"
            case 3: return "循环录像"
            case 4: return "TimeWarp"
            default: return "子模式\(sub)"
            }
        case .photo:
            switch sub {
            case 0: return "单张拍照"
            case 1: return "连拍"
            case 2: return "夜景拍照"
            default: return "子模式\(sub)"
            }
        case .multiShot:
            switch sub {
            case 0: return "Burst 连拍"
            case 1: return "延时拍照(TimeLapse)"
            case 2: return "夜景延时"
            default: return "子模式\(sub)"
            }
        case .unknown:
            return "子模式\(sub)"
        }
    }

    private static func intValue(_ any: Any?) -> Int? {
        if let i = any as? Int { return i }
        if let n = any as? NSNumber { return n.intValue }
        if let s = any as? String { return Int(s) }
        return nil
    }

    private static func formatDuration(_ sec: Int) -> String {
        let s = max(0, sec)
        let m = s / 60
        let r = s % 60
        return String(format: "%d:%02d", m, r)
    }
}
