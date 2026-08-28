import AVFoundation
import UIKit

final class ReadingCameraService: NSObject {
    private let session = AVCaptureSession()
    private let photoOutput = AVCapturePhotoOutput()
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var captureCompletion: ((Data?, String?) -> Void)?
    private var currentPosition: AVCaptureDevice.Position = .back
    private let sessionQueue = DispatchQueue(label: "legacy.reading.camera.session")

    var cameraPosition: AVCaptureDevice.Position {
        currentPosition
    }

    func attachPreview(to view: UIView) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            if self.previewLayer == nil {
                let layer = AVCaptureVideoPreviewLayer(session: self.session)
                layer.videoGravity = .resizeAspectFill
                self.previewLayer = layer
                view.layer.insertSublayer(layer, at: 0)
            }
            self.previewLayer?.frame = view.bounds
            self.updatePreviewMirroring()
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
            configureSession(position: .back, completion: completion)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    if granted {
                        self?.configureSession(position: .back, completion: completion)
                    } else {
                        completion(false, "需要相机权限才能开启阅读模式")
                    }
                }
            }
        default:
            completion(false, "请在系统设置中允许相机权限")
        }
    }

    func stop() {
        sessionQueue.sync { [weak self] in
            guard let self = self else { return }
            if self.session.isRunning {
                self.session.stopRunning()
            }
        }
    }

    func switchCamera(completion: @escaping (Bool, String) -> Void) {
        let next: AVCaptureDevice.Position = currentPosition == .back ? .front : .back
        configureSession(position: next, completion: completion)
    }

    func capturePhoto(completion: @escaping (Data?, String?) -> Void) {
        sessionQueue.async { [weak self] in
            guard let self = self else { return }
            guard self.session.isRunning else {
                DispatchQueue.main.async { completion(nil, "相机未就绪") }
                return
            }
            self.captureCompletion = completion
            let settings = AVCapturePhotoSettings()
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
    }

    private func configureSession(position: AVCaptureDevice.Position, completion: @escaping (Bool, String) -> Void) {
        sessionQueue.async { [weak self] in
            guard let self = self else { return }
            if self.session.isRunning {
                self.session.stopRunning()
            }

            self.session.beginConfiguration()
            self.session.sessionPreset = .photo
            for input in self.session.inputs {
                self.session.removeInput(input)
            }
            for output in self.session.outputs {
                self.session.removeOutput(output)
            }

            guard
                let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: position),
                let input = try? AVCaptureDeviceInput(device: device),
                self.session.canAddInput(input)
            else {
                self.session.commitConfiguration()
                let message = position == .front ? "本机没有可用前置摄像头" : "本机没有可用后置摄像头"
                DispatchQueue.main.async { completion(false, message) }
                return
            }

            self.session.addInput(input)
            if self.session.canAddOutput(self.photoOutput) {
                self.session.addOutput(self.photoOutput)
            }
            self.session.commitConfiguration()
            self.currentPosition = position
            self.session.startRunning()

            DispatchQueue.main.async {
                self.updatePreviewMirroring()
                completion(true, "")
            }
        }
    }

    private func updatePreviewMirroring() {
        guard let connection = previewLayer?.connection else { return }
        guard connection.isVideoMirroringSupported else { return }
        connection.automaticallyAdjustsVideoMirroring = false
        connection.isVideoMirrored = currentPosition == .front
    }
}

extension ReadingCameraService: AVCapturePhotoCaptureDelegate {
    func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        let finish: (Data?, String?) -> Void = { data, err in
            DispatchQueue.main.async { [weak self] in
                self?.captureCompletion?(data, err)
                self?.captureCompletion = nil
            }
        }
        if let error = error {
            finish(nil, error.localizedDescription)
            return
        }
        guard let data = photo.fileDataRepresentation() else {
            finish(nil, "拍照失败：无图像数据")
            return
        }
        finish(data, nil)
    }
}
