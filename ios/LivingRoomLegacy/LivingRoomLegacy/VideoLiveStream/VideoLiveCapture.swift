import AVFoundation
import UIKit

final class VideoLiveCapture: NSObject {
    static let width = 640
    static let height = 480
    static let fps = 15

    let session = AVCaptureSession()
    var onFrame: ((CMSampleBuffer) -> Void)?

    private(set) var isRunning = false
    private(set) var hasDevice = false
    private(set) var statusMessage = ""

    private let sessionQueue = DispatchQueue(label: "legacy.video.live.capture")
    private let output = AVCaptureVideoDataOutput()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var configured = false

    func attachPreview(to view: UIView) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if self.previewLayer == nil {
                let layer = AVCaptureVideoPreviewLayer(session: self.session)
                layer.videoGravity = .resizeAspectFill
                self.previewLayer = layer
                view.layer.insertSublayer(layer, at: 0)
            }
            self.previewLayer?.frame = view.bounds
        }
    }

    func layoutPreview(in view: UIView) {
        DispatchQueue.main.async { [weak self] in
            self?.previewLayer?.frame = view.bounds
        }
    }

    func start(completion: @escaping (Bool, String) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            sessionQueue.async { [weak self] in
                self?.configureAndRun(completion: completion)
            }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                guard let self else { return }
                if granted {
                    self.sessionQueue.async {
                        self.configureAndRun(completion: completion)
                    }
                } else {
                    DispatchQueue.main.async {
                        completion(false, "直播需要相机权限（设置 → 相机）。")
                    }
                }
            }
        default:
            completion(false, "直播需要相机权限（设置 → 相机）。")
        }
    }

    func stop() {
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
            DispatchQueue.main.async { self.isRunning = false }
        }
    }

    private func configureAndRun(completion: @escaping (Bool, String) -> Void) {
        if !configured {
            session.beginConfiguration()
            if session.canSetSessionPreset(.vga640x480) {
                session.sessionPreset = .vga640x480
            } else {
                session.sessionPreset = .medium
            }
            for input in session.inputs { session.removeInput(input) }
            for output in session.outputs { session.removeOutput(output) }

            guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
                    ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
                  let input = try? AVCaptureDeviceInput(device: device),
                  session.canAddInput(input) else {
                session.commitConfiguration()
                DispatchQueue.main.async {
                    self.hasDevice = false
                    completion(false, "本机没有可用摄像头。")
                }
                return
            }
            session.addInput(input)

            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            ]
            output.setSampleBufferDelegate(self, queue: sessionQueue)
            if session.canAddOutput(output) {
                session.addOutput(output)
            }

            if let conn = output.connection(with: .video), conn.isVideoOrientationSupported {
                conn.videoOrientation = .portrait
            }

            try? device.lockForConfiguration()
            let desired = CMTime(value: 1, timescale: CMTimeScale(Self.fps))
            device.activeVideoMinFrameDuration = desired
            device.activeVideoMaxFrameDuration = desired
            device.unlockForConfiguration()

            session.commitConfiguration()
            configured = true
            hasDevice = true
        }

        if !session.isRunning {
            session.startRunning()
        }
        isRunning = true
        statusMessage = ""
        DispatchQueue.main.async { completion(true, "") }
    }
}

extension VideoLiveCapture: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        onFrame?(sampleBuffer)
    }
}
