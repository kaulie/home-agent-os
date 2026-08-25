import AVFoundation
import SwiftUI
import UIKit

/// Dedicated photo workspace: live rear preview + one shutter tap. Capture success
/// lands the photo in the local list immediately; assets/upload runs in the
/// background per photo and never blocks the next shot.
struct PhotoWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    var onClose: () -> Void
    @StateObject private var camera = RearCameraController()
    @StateObject private var clicks = ClickGuard()
    @State private var reviewImage: UIImage?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            GeometryReader { geo in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        cameraStage
                            .frame(width: geo.size.width, height: geo.size.height)
                        photoTimeline
                            .padding(.top, 20)
                    }
                }
            }
        }
        .ignoresSafeArea()
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .onAppear {
            camera.start()
        }
        .onDisappear {
            camera.stop()
            reviewImage = nil
        }
    }

    private var cameraStage: some View {
        ZStack(alignment: .topLeading) {
            VStack(spacing: 0) {
                previewBlock
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                shutterBar
            }
            Button {
                onClose()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
            }
            .accessibilityLabel("关闭拍照")
            .padding(.top, 54)
            .padding(.leading, 12)
        }
    }

    private var permissionHint: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(camera.statusMessage)
                .font(.system(size: 13, weight: .medium, design: .rounded))
                .foregroundStyle(Color.orange.opacity(0.95))
                .fixedSize(horizontal: false, vertical: true)
            if camera.authorization == .denied || camera.authorization == .restricted {
                Button("去设置") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(EdgeTheme.sand)
            }
        }
    }

    private var previewBlock: some View {
        ZStack {
            Color.black
            if let reviewImage {
                Image(uiImage: reviewImage)
                    .resizable()
                    .scaledToFill()
                    .clipped()
                    .accessibilityLabel("刚拍的照片")
            } else if camera.authorization == .authorized, camera.hasDevice {
                CameraPreviewView(session: camera.session)
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "camera")
                        .font(.system(size: 36, weight: .light))
                        .foregroundStyle(EdgeTheme.sand)
                    Text(camera.authorization != .authorized ? "需要相机权限" : "本机没有可用摄像头")
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                    Text(camera.authorization != .authorized ? "授权后即可取景拍照。" : "模拟器无法预览，请用真机。")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                    if camera.authorization == .denied || camera.authorization == .restricted {
                        permissionHint
                    }
                }
                .padding(.horizontal, 24)
            }
            if reviewImage == nil, !model.photoHint.isEmpty {
                VStack {
                    Spacer()
                    Text(model.photoHint)
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(Color.black.opacity(0.55), in: Capsule())
                        .padding(.bottom, 16)
                }
            }
        }
        .clipped()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var shutterBar: some View {
        ZStack {
            Color.black
            if reviewImage != nil {
                VStack(spacing: 8) {
                    captureBanner
                    if !model.photoHint.isEmpty {
                        Button("继续拍") {
                            model.setPhotoHint("")
                            withAnimation(.easeOut(duration: 0.18)) {
                                reviewImage = nil
                            }
                        }
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    }
                }
            } else {
                HStack(alignment: .center) {
                    flashButton
                    Spacer()
                    shutterButton
                    Spacer()
                    flipButton
                }
                .padding(.horizontal, 36)
            }
        }
        .frame(height: 118)
        .padding(.bottom, 28)
        .frame(maxWidth: .infinity)
        .background(Color.black)
    }

    private var flashButton: some View {
        Button {
            camera.toggleFlash()
        } label: {
            Image(systemName: camera.flashOn ? "bolt.fill" : "bolt.slash.fill")
                .font(.system(size: 22, weight: .medium))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
        }
        .disabled(!camera.hasTorch || camera.capturing)
        .opacity(camera.hasTorch ? 1 : 0.35)
        .accessibilityLabel(camera.flashOn ? "关闭闪光灯" : "打开闪光灯")
    }

    private var flipButton: some View {
        Button {
            camera.flipCamera()
        } label: {
            Image(systemName: "arrow.triangle.2.circlepath.camera")
                .font(.system(size: 22, weight: .medium))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
        }
        .disabled(camera.capturing || !camera.isRunning)
        .accessibilityLabel("翻转摄像头")
    }

    private var shutterButton: some View {
        Button {
            takePhoto()
        } label: {
            ZStack {
                Circle()
                    .stroke(Color.white.opacity(0.92), lineWidth: 5)
                    .frame(width: 76, height: 76)
                Circle()
                    .fill(Color.white)
                    .frame(width: 62, height: 62)
            }
        }
        .buttonStyle(.plain)
        .disabled(camera.capturing || !camera.isReady)
        .accessibilityLabel("拍照")
        .accessibilityHint("拍一张，成片出来后再上传")
    }

    /// Shown over the just-captured frame. Capture is acknowledged immediately;
    /// the background upload state lives on the photo's own timeline row.
    private var captureBanner: some View {
        HStack(spacing: 10) {
            if !model.photoHint.isEmpty {
                Text(model.photoHint)
                    .lineLimit(3)
            } else {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(EdgeTheme.sand)
                Text("已拍照 · 后台自动上传")
            }
        }
        .font(.system(size: 15, weight: .semibold, design: .rounded))
        .foregroundStyle(Color.white.opacity(0.94))
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(EdgeTheme.ink.opacity(0.78), in: Capsule())
        .padding(.horizontal, 16)
        .accessibilityLabel(model.photoHint.isEmpty ? "已拍照，后台自动上传" : model.photoHint)
    }

    private var photoTimeline: some View {
        VStack(alignment: .leading, spacing: 10) {
            EdgeTheme.sectionLabel("最近")
                .padding(.horizontal, 20)
            if model.photoTurns.isEmpty {
                Text("还没有照片。对准后点快门，拍完自动上传。")
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 28)
            } else {
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(model.photoTurns) { turn in
                        MediaTimelineRow(
                            turn: turn,
                            accessibilityNoun: "照片",
                            onRetryUpload: { model.retryPhotoUpload(turnId: turn.id) }
                        )
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 28)
            }
        }
        .frame(maxWidth: .infinity, alignment: .top)
    }

    private func takePhoto() {
        guard clicks.tryTap(cooldown: 0.8) else { return }
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setPhotoHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        guard camera.isReady else {
            model.setPhotoHint(camera.statusMessage.isEmpty ? "拍照失败：相机未就绪。" : camera.statusMessage)
            return
        }
        model.setPhotoHint("")
        Task {
            do {
                let image = try await camera.capturePhoto()
                withAnimation(.easeOut(duration: 0.18)) {
                    reviewImage = image
                }
                // Capture succeeded: register locally right away, upload in background.
                model.registerLocalIPhonePhoto(image: image)
                if model.photoHint.isEmpty {
                    try? await Task.sleep(nanoseconds: 700_000_000)
                    withAnimation(.easeOut(duration: 0.18)) {
                        reviewImage = nil
                    }
                }
            } catch let e as VisualInput.InputError where e.isCancelled {
                return
            } catch {
                model.setPhotoHint(error.localizedDescription)
            }
        }
    }
}

// MARK: - Camera

final class RearCameraController: NSObject, ObservableObject {
    enum Authorization {
        case unknown
        case authorized
        case denied
        case restricted
        case undetermined
    }

    let session = AVCaptureSession()
    @Published private(set) var authorization: Authorization = .unknown
    @Published private(set) var hasDevice = false
    @Published private(set) var isRunning = false
    @Published private(set) var capturing = false
    @Published private(set) var statusMessage = ""
    @Published private(set) var flashOn = false
    @Published private(set) var hasTorch = false
    @Published private(set) var cameraPosition: AVCaptureDevice.Position = .back

    var isReady: Bool { authorization == .authorized && hasDevice && isRunning && !capturing }

    private let sessionQueue = DispatchQueue(label: "homeagent.iphone.photo.session")
    private let photoOutput = AVCapturePhotoOutput()
    private var videoInput: AVCaptureDeviceInput?
    private var configured = false
    private var photoContinuation: CheckedContinuation<UIImage, Error>?

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

    func capturePhoto() async throws -> UIImage {
        guard isReady else {
            throw VisualInput.InputError.message("拍照失败：相机未就绪。")
        }
        capturing = true
        defer { capturing = false }
        let useFlash = flashOn
        return try await withCheckedThrowingContinuation { cont in
            if photoContinuation != nil {
                cont.resume(throwing: VisualInput.InputError.message("拍照失败：正在拍照。"))
                return
            }
            photoContinuation = cont
            sessionQueue.async { [weak self] in
                guard let self else { return }
                let settings = AVCapturePhotoSettings()
                let mode: AVCaptureDevice.FlashMode = useFlash ? .on : .off
                if self.photoOutput.supportedFlashModes.contains(mode) {
                    settings.flashMode = mode
                }
                self.photoOutput.capturePhoto(with: settings, delegate: self)
            }
        }
    }

    func toggleFlash() {
        sessionQueue.async { [weak self] in
            guard let self, let device = self.videoInput?.device, device.hasTorch else { return }
            do {
                try device.lockForConfiguration()
                if device.torchMode == .on {
                    device.torchMode = .off
                } else {
                    try device.setTorchModeOn(level: 1.0)
                }
                device.unlockForConfiguration()
                let on = device.torchMode == .on
                DispatchQueue.main.async { self.flashOn = on }
            } catch {
                DispatchQueue.main.async {
                    self.statusMessage = "闪光灯不可用。"
                }
            }
        }
    }

    func flipCamera() {
        sessionQueue.async { [weak self] in
            self?.swapCamera()
        }
    }

    private func startSession() async {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        switch status {
        case .authorized:
            authorization = .authorized
        case .denied:
            authorization = .denied
            statusMessage = "拍照失败：相机权限未开（设置 → 相机）。"
            return
        case .restricted:
            authorization = .restricted
            statusMessage = "拍照失败：相机权限未开（设置 → 相机）。"
            return
        case .notDetermined:
            authorization = .undetermined
            let ok = await AVCaptureDevice.requestAccess(for: .video)
            authorization = ok ? .authorized : .denied
            if !ok {
                statusMessage = "拍照失败：需要相机权限（设置 → 相机）。"
                return
            }
        @unknown default:
            authorization = .denied
            statusMessage = "拍照失败：无法确认相机权限。"
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
            session.sessionPreset = .photo
            let attached = attachCamera(position: .back) || attachCamera(position: .front)
            guard attached else {
                session.commitConfiguration()
                DispatchQueue.main.async {
                    self.hasDevice = false
                    self.statusMessage = "本机没有可用摄像头。"
                }
                return
            }
            if session.canAddOutput(photoOutput) {
                session.addOutput(photoOutput)
            }
            session.commitConfiguration()
            configured = true
            publishDeviceState()
        }
        if !session.isRunning {
            session.startRunning()
        }
        DispatchQueue.main.async { self.isRunning = true }
    }

    @discardableResult
    private func attachCamera(position: AVCaptureDevice.Position) -> Bool {
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: position),
              let input = try? AVCaptureDeviceInput(device: device) else {
            return false
        }
        if session.canAddInput(input) {
            session.addInput(input)
            videoInput = input
            return true
        }
        return false
    }

    private func swapCamera() {
        let next: AVCaptureDevice.Position = (videoInput?.device.position == .front) ? .back : .front
        session.beginConfiguration()
        if let current = videoInput {
            session.removeInput(current)
            videoInput = nil
        }
        let attached = attachCamera(position: next)
        if !attached {
            _ = attachCamera(position: next == .front ? .back : .front)
        }
        if let device = videoInput?.device, device.hasTorch, device.torchMode != .off {
            try? device.lockForConfiguration()
            device.torchMode = .off
            device.unlockForConfiguration()
        }
        session.commitConfiguration()
        publishDeviceState()
    }

    private func publishDeviceState() {
        let device = videoInput?.device
        DispatchQueue.main.async {
            self.hasDevice = device != nil
            self.hasTorch = device?.hasTorch == true
            self.flashOn = device?.torchMode == .on
            self.cameraPosition = device?.position ?? .back
            if device == nil {
                self.statusMessage = "本机没有可用摄像头。"
            }
        }
    }
}

extension RearCameraController: AVCapturePhotoCaptureDelegate {
    nonisolated func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        let result: Result<UIImage, Error>
        if let error {
            result = .failure(VisualInput.InputError.message("拍照失败：\(error.localizedDescription)"))
        } else if let data = photo.fileDataRepresentation(), let image = UIImage(data: data) {
            result = .success(image)
        } else {
            result = .failure(VisualInput.InputError.message("拍照失败：无法读取照片。"))
        }
        DispatchQueue.main.async { [weak self] in
            self?.finishPhoto(result)
        }
    }

    @MainActor
    private func finishPhoto(_ result: Result<UIImage, Error>) {
        guard let cont = photoContinuation else { return }
        photoContinuation = nil
        cont.resume(with: result)
    }
}

private struct CameraPreviewView: UIViewRepresentable {
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
