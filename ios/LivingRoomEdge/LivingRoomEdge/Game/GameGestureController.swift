import AVFoundation
import Foundation
import Vision

/// Vision body pose → simple gesture GameCommands (no LLM).
@MainActor
final class GameGestureController: NSObject, ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var lastError: String = ""
    @Published private(set) var previewLayer: AVCaptureVideoPreviewLayer?

    /// Created on first start() — eager AVCaptureSession init at tab load has hung launch.
    private var session: AVCaptureSession?
    private let queue = DispatchQueue(label: "game.gesture.pose")
    private var lastSample: (centerX: CGFloat, leftWrist: CGPoint?, rightWrist: CGPoint?, ts: CFTimeInterval)?
    private var neutralCenterX: CGFloat?
    private var calibrateUntil: CFTimeInterval = 0
    private var lastCommandAt: CFTimeInterval = 0
    private var handsUpSince: CFTimeInterval?
    var onCommand: ((GameCommand) -> Void)?

    func start() async {
        lastError = ""
        guard !isRunning else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            break
        case .notDetermined:
            let ok = await AVCaptureDevice.requestAccess(for: .video)
            guard ok else {
                lastError = "未授权相机"
                return
            }
        default:
            lastError = "相机权限未开"
            return
        }
        configureSession()
        calibrateUntil = CACurrentMediaTime() + 1.0
        neutralCenterX = nil
        let captureSession = ensureSession()
        queue.async {
            captureSession.startRunning()
        }
        isRunning = true
    }

    func stop() {
        if let session {
            queue.async {
                session.stopRunning()
            }
        }
        isRunning = false
    }

    private func ensureSession() -> AVCaptureSession {
        if let session { return session }
        let next = AVCaptureSession()
        session = next
        return next
    }

    private func configureSession() {
        let session = ensureSession()
        session.beginConfiguration()
        session.sessionPreset = .vga640x480
        session.inputs.forEach { session.removeInput($0) }
        session.outputs.forEach { session.removeOutput($0) }
        guard
            let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
            let input = try? AVCaptureDeviceInput(device: device)
        else {
            lastError = "无法打开前置摄像头"
            session.commitConfiguration()
            return
        }
        if session.canAddInput(input) { session.addInput(input) }
        let output = AVCaptureVideoDataOutput()
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        session.commitConfiguration()
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        previewLayer = layer
    }

    private func processPose(_ observation: VNHumanBodyPoseObservation, ts: CFTimeInterval) {
        func point(_ joint: VNHumanBodyPoseObservation.JointName) -> CGPoint? {
            guard let p = try? observation.recognizedPoint(joint), p.confidence > 0.3 else { return nil }
            return CGPoint(x: p.location.x, y: p.location.y)
        }
        let ls = point(.leftShoulder)
        let rs = point(.rightShoulder)
        let lw = point(.leftWrist)
        let rw = point(.rightWrist)
        let root = point(.root)
        guard let ls, let rs else { return }
        let centerX = root?.x ?? (ls.x + rs.x) / 2
        if ts < calibrateUntil {
            neutralCenterX = centerX
            return
        }
        let neutral = neutralCenterX ?? centerX
        if ts - lastCommandAt < 0.12 { return }

        if let lw, let rw, lw.y > ls.y + 0.08, rw.y > rs.y + 0.08 {
            if handsUpSince == nil { handsUpSince = ts }
            if let since = handsUpSince, ts - since > 0.2 {
                fire(.jump, ts: ts)
                handsUpSince = nil
            }
        } else {
            handsUpSince = nil
        }

        if let prev = lastSample, ts - prev.ts <= 0.35 {
            if let pl = prev.leftWrist, let cl = lw {
                let vx = (cl.x - pl.x) / CGFloat(ts - prev.ts)
                if vx < -0.35 { fire(.moveLeft, ts: ts); return }
            }
            if let pr = prev.rightWrist, let cr = rw {
                let vx = (cr.x - pr.x) / CGFloat(ts - prev.ts)
                if vx > 0.35 { fire(.moveRight, ts: ts); return }
            }
            if let pr = prev.rightWrist ?? prev.leftWrist, let cr = rw ?? lw {
                let vx = (cr.x - pr.x) / CGFloat(ts - prev.ts)
                if vx < -0.35 { fire(.moveLeft, ts: ts); return }
                if vx > 0.35 { fire(.moveRight, ts: ts); return }
            }
        }

        let dx = centerX - neutral
        if dx < -0.08 { fire(.moveLeft, ts: ts); return }
        if dx > 0.08 { fire(.moveRight, ts: ts); return }

        lastSample = (centerX, lw, rw, ts)
    }

    private func fire(_ type: GameCommandType, ts: CFTimeInterval) {
        lastCommandAt = ts
        let cmd = GameCommand(type: type, source: .gesture)
        Task { @MainActor in
            onCommand?(cmd)
            GameSession.shared.noteCommand(type, source: .gesture)
        }
    }
}

extension GameGestureController: AVCaptureVideoDataOutputSampleBufferDelegate {
    nonisolated func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixel = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let request = VNDetectHumanBodyPoseRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: pixel, orientation: .leftMirrored, options: [:])
        do {
            try handler.perform([request])
            guard let obs = request.results?.first else { return }
            let ts = CACurrentMediaTime()
            Task { @MainActor in
                self.processPose(obs, ts: ts)
            }
        } catch {}
    }
}
