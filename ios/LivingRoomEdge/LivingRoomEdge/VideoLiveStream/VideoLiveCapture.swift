import AVFoundation
import SwiftUI
import UIKit

final class VideoLiveCapture: NSObject, ObservableObject {
    let session = AVCaptureSession()
    @Published private(set) var authorization: AVAuthorizationStatus = .notDetermined
    @Published private(set) var isRunning = false
    @Published private(set) var hasDevice = false
    @Published private(set) var width = 1920
    @Published private(set) var height = 1080
    @Published private(set) var fps = 30
    @Published private(set) var statusMessage = ""

    var onFrame: ((CMSampleBuffer) -> Void)?

    private let sessionQueue = DispatchQueue(label: "homeagent.video.live.capture")
    private let output = AVCaptureVideoDataOutput()
    private var configured = false

    func start() {
        Task { await startSession() }
    }

    func stop() {
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
            DispatchQueue.main.async { self.isRunning = false }
        }
    }

    private func startSession() async {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        authorization = status
        switch status {
        case .authorized:
            break
        case .notDetermined:
            let ok = await AVCaptureDevice.requestAccess(for: .video)
            authorization = ok ? .authorized : .denied
            if !ok {
                statusMessage = "直播失败：需要相机权限（设置 → 相机）。"
                return
            }
        case .denied, .restricted:
            statusMessage = "直播失败：相机权限未开（设置 → 相机）。"
            return
        @unknown default:
            statusMessage = "直播失败：无法确认相机权限。"
            return
        }
        statusMessage = ""
        sessionQueue.async { [weak self] in
            self?.configureAndRun()
        }
    }

    private func configureAndRun() {
        if !configured {
            session.beginConfiguration()
            var preset: AVCaptureSession.Preset = .hd1920x1080
            var w = 1920
            var h = 1080
            var rate = 30
            if session.canSetSessionPreset(.hd1920x1080) {
                session.sessionPreset = .hd1920x1080
            } else if session.canSetSessionPreset(.hd1280x720) {
                session.sessionPreset = .hd1280x720
                preset = .hd1280x720
                w = 1280
                h = 720
                rate = 15
            } else {
                session.sessionPreset = .high
                preset = .high
            }
            _ = preset
            guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
                    ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
                  let input = try? AVCaptureDeviceInput(device: device) else {
                session.commitConfiguration()
                DispatchQueue.main.async {
                    self.hasDevice = false
                    self.statusMessage = "本机没有可用摄像头。"
                }
                return
            }
            if session.canAddInput(input) {
                session.addInput(input)
            }
            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            ]
            output.setSampleBufferDelegate(self, queue: sessionQueue)
            if session.canAddOutput(output) {
                session.addOutput(output)
            }
            // Keep sensor landscape so encoder size matches 1920x1080 / 1280x720.
            if let conn = output.connection(with: .video) {
                if conn.isVideoOrientationSupported {
                    conn.videoOrientation = .landscapeRight
                }
                if conn.isVideoMirroringSupported {
                    conn.isVideoMirrored = false
                }
            }
            try? device.lockForConfiguration()
            let desired = CMTime(value: 1, timescale: CMTimeScale(rate))
            device.activeVideoMinFrameDuration = desired
            device.activeVideoMaxFrameDuration = desired
            let dims = CMVideoFormatDescriptionGetDimensions(device.activeFormat.formatDescription)
            if dims.width > 0, dims.height > 0 {
                w = Int(dims.width)
                h = Int(dims.height)
            }
            device.unlockForConfiguration()
            session.commitConfiguration()
            configured = true
            DispatchQueue.main.async {
                self.hasDevice = true
                self.width = w
                self.height = h
                self.fps = rate
            }
        }
        if !session.isRunning {
            session.startRunning()
        }
        DispatchQueue.main.async { self.isRunning = true }
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

struct LiveCameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        uiView.previewLayer.session = session
    }

    final class PreviewUIView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }
}
