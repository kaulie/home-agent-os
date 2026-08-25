import Foundation

/// iPhone-only `camera.capture`. **Not** the Mac pipeline.
///
/// Mac (`gopro_camera.py` + `wifi_switch.py`) switches home↔GoPro Wi‑Fi.
/// iPhone does not join/switch Wi‑Fi; it talks to gpControl at the camera HTTP
/// endpoint and writes a local inbox capture. Upload is `asset.upload`. No SSID /
/// hotspot settings.
enum GoProCapture {
    struct Result {
        let message: String
        let outputs: [String: Any]
    }

    /// Called after each in-step action completes: `(name, durationMs)`.
    typealias ActionCompleteHandler = (String, Int) async -> Void
    /// Called when an action starts (so the app can show 正在上传 before the wait).
    typealias ActionBeginHandler = (String) async -> Void

    static func run(
        intentId: String,
        params: [String: Any],
        intentURL: String,
        onActionBegin: ActionBeginHandler? = nil,
        onActionComplete: ActionCompleteHandler? = nil
    ) async throws -> Result {
        let driver = GoProDriver()
        let timer = StageTimer()
        _ = params
        _ = onActionBegin

        timer.begin("connect")
        do {
            try await driver.connect()
        } catch {
            throw captureError("拍照失败：连不上 GoPro。（\(error.localizedDescription)）")
        }
        await reportAction("connect", timer: timer, handler: onActionComplete)

        timer.begin("capture")
        _ = try await driver.capturePhoto()
        try await Task.sleep(nanoseconds: 2_000_000_000)
        await reportAction("capture", timer: timer, handler: onActionComplete)

        timer.begin("media_list")
        let list = try await driver.fetchMediaList()
        await reportAction("media_list", timer: timer, handler: onActionComplete)

        guard let item = await driver.latestStillItem(fromMediaListJSON: list.body) else {
            throw captureError("拍照失败：相机媒体库里没有照片。")
        }

        timer.begin("download")
        let file = try await driver.downloadMedia(path: item.path)
        let stored = try CaptureStore.put(jpeg: file.data, originalName: item.name)
        await reportAction("download", timer: timer, handler: onActionComplete)

        let marks = timer.finish()
        let outputs: [String: Any] = [
            "capture_ref": stored.json,
            "action_timings": marks,
        ]
        let timingLines = marks.keys.sorted().map { key in
            "\(key)=\(marks[key] ?? 0)ms"
        }.joined(separator: "\n")
        return Result(
            message: """
            capture ok (local inbox, no asset) (iphone, no wifi switch)
            capture_id: \(stored.captureId)
            timings:
            \(timingLines)
            """,
            outputs: outputs
        )
    }

    private static func reportAction(
        _ name: String,
        timer: StageTimer,
        handler: ActionCompleteHandler?
    ) async {
        let ms = timer.end(name)
        await handler?(name, ms)
    }

    private static func captureError(_ message: String) -> NSError {
        NSError(domain: "GoProCapture", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private final class StageTimer: @unchecked Sendable {
        private let lock = NSLock()
        private let t0 = CFAbsoluteTimeGetCurrent()
        private var open: [String: CFAbsoluteTime] = [:]
        private var marks: [String: Int] = [:]

        func begin(_ name: String) {
            lock.lock()
            defer { lock.unlock() }
            open[name] = CFAbsoluteTimeGetCurrent()
        }

        func end(_ name: String) -> Int {
            lock.lock()
            defer { lock.unlock() }
            let start = open.removeValue(forKey: name) ?? CFAbsoluteTimeGetCurrent()
            let ms = Int((CFAbsoluteTimeGetCurrent() - start) * 1000)
            marks[name] = ms
            return ms
        }

        func finish() -> [String: Int] {
            lock.lock()
            defer { lock.unlock() }
            marks["total"] = Int((CFAbsoluteTimeGetCurrent() - t0) * 1000)
            return marks
        }
    }
}
