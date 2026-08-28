import UIKit

final class ReadingCaptureViewController: UIViewController {
    var onExit: (() -> Void)?
    var onPhotoCaptured: ((String) -> Void)?
    var onPhotoUploadChanged: (() -> Void)?

    private let camera = ReadingCameraService()
    private let speech = ReadingSpeechService()

    private let previewView = UIView()
    private let backButton = UIButton(type: .system)
    private let flipButton = UIButton(type: .system)
    private let hintLabel = UILabel()
    private let statusLabel = UILabel()
    private let micButton = UIButton(type: .system)
    private let captureButton = UIButton(type: .system)

    private var micEnabled = false
    private var sessionStarted = false
    private var restartWorkItem: DispatchWorkItem?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        speech.delegate = self
        setupUI()
    }

    func startSession() {
        guard !sessionStarted else {
            camera.attachPreview(to: previewView)
            return
        }
        hintLabel.text = "正在打开相机…"
        camera.start { [weak self] ok, _ in
            guard let self = self else { return }
            if ok {
                self.sessionStarted = true
                self.camera.attachPreview(to: self.previewView)
                self.hintLabel.text = "对准书本"
                self.statusLabel.text = "点「说话」或「拍照」"
            } else {
                self.hintLabel.text = "相机打不开，请找家长"
            }
        }
    }

    func stopSession() {
        restartWorkItem?.cancel()
        if micEnabled {
            toggleMic()
        }
        camera.stop()
        speech.stop()
        sessionStarted = false
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        camera.layoutPreview(in: previewView)
    }

    private func setupUI() {
        previewView.backgroundColor = UIColor(white: 0.12, alpha: 1)
        previewView.translatesAutoresizingMaskIntoConstraints = false

        backButton.setTitle(" 返回", for: .normal)
        backButton.setTitleColor(.white, for: .normal)
        backButton.titleLabel?.font = LegacyTheme.fontHint
        backButton.backgroundColor = UIColor(white: 0, alpha: 0.45)
        backButton.layer.cornerRadius = 20
        backButton.contentEdgeInsets = UIEdgeInsets(top: 8, left: 12, bottom: 8, right: 14)
        backButton.addTarget(self, action: #selector(backTapped), for: .touchUpInside)
        backButton.translatesAutoresizingMaskIntoConstraints = false

        flipButton.setTitle(" 翻转", for: .normal)
        flipButton.setTitleColor(.white, for: .normal)
        flipButton.titleLabel?.font = LegacyTheme.fontHint
        flipButton.backgroundColor = UIColor(white: 0, alpha: 0.45)
        flipButton.layer.cornerRadius = 20
        flipButton.contentEdgeInsets = UIEdgeInsets(top: 8, left: 12, bottom: 8, right: 14)
        flipButton.addTarget(self, action: #selector(flipTapped), for: .touchUpInside)
        flipButton.translatesAutoresizingMaskIntoConstraints = false

        hintLabel.font = LegacyTheme.fontTitle
        hintLabel.textColor = .white
        hintLabel.textAlignment = .center
        hintLabel.text = "对准书本"
        hintLabel.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = LegacyTheme.fontHint
        statusLabel.textColor = UIColor(white: 0.92, alpha: 1)
        statusLabel.textAlignment = .center
        statusLabel.numberOfLines = 2
        statusLabel.text = "点「说话」或「拍照」"
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        styleActionButton(micButton, title: "说话", filled: false)
        micButton.addTarget(self, action: #selector(toggleMicTapped), for: .touchUpInside)

        styleActionButton(captureButton, title: "拍照", filled: true)
        captureButton.addTarget(self, action: #selector(captureTapped), for: .touchUpInside)

        view.addSubview(previewView)
        view.addSubview(backButton)
        view.addSubview(flipButton)
        view.addSubview(hintLabel)
        view.addSubview(statusLabel)
        view.addSubview(micButton)
        view.addSubview(captureButton)

        NSLayoutConstraint.activate([
            previewView.topAnchor.constraint(equalTo: view.topAnchor),
            previewView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            previewView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            previewView.bottomAnchor.constraint(equalTo: view.bottomAnchor),

            backButton.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            backButton.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 12),

            flipButton.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            flipButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -12),

            hintLabel.topAnchor.constraint(equalTo: backButton.bottomAnchor, constant: 12),
            hintLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            hintLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            statusLabel.topAnchor.constraint(equalTo: hintLabel.bottomAnchor, constant: 8),
            statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            micButton.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            micButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -20),
            micButton.heightAnchor.constraint(equalToConstant: 56),

            captureButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            captureButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -20),
            captureButton.leadingAnchor.constraint(equalTo: micButton.trailingAnchor, constant: 16),
            captureButton.heightAnchor.constraint(equalToConstant: 56),
            captureButton.widthAnchor.constraint(equalTo: micButton.widthAnchor),
        ])
    }

    private func styleActionButton(_ button: UIButton, title: String, filled: Bool) {
        button.setTitle(title, for: .normal)
        button.titleLabel?.font = LegacyTheme.fontButton
        button.layer.cornerRadius = 16
        button.translatesAutoresizingMaskIntoConstraints = false
        if filled {
            button.setTitleColor(.white, for: .normal)
            button.backgroundColor = LegacyTheme.accent
        } else {
            button.setTitleColor(.white, for: .normal)
            button.backgroundColor = UIColor(white: 0.22, alpha: 0.92)
            button.layer.borderWidth = 2
            button.layer.borderColor = UIColor.white.withAlphaComponent(0.35).cgColor
        }
    }

    @objc private func backTapped() {
        onExit?()
    }

    @objc private func flipTapped() {
        guard sessionStarted else { return }
        flipButton.isEnabled = false
        statusLabel.text = "切换摄像头…"
        camera.switchCamera { [weak self] ok, message in
            guard let self = self else { return }
            self.flipButton.isEnabled = true
            if ok {
                self.camera.attachPreview(to: self.previewView)
                self.hintLabel.text = self.camera.cameraPosition == .front ? "前置摄像头" : "对准书本"
                self.statusLabel.text = "点「说话」或「拍照」"
            } else {
                self.statusLabel.text = message.isEmpty ? "切换失败" : message
            }
        }
    }

    @objc private func toggleMicTapped() {
        toggleMic()
    }

    private func toggleMic() {
        if micEnabled {
            micEnabled = false
            speech.stop()
            styleActionButton(micButton, title: "说话", filled: false)
            statusLabel.text = "点「说话」或「拍照」"
            VoiceTraceLog.append(kind: .status, text: "麦克风已关闭")
        } else {
            micEnabled = true
            micButton.backgroundColor = LegacyTheme.accent
            micButton.layer.borderWidth = 0
            micButton.setTitle("正在听", for: .normal)
            statusLabel.text = "说吧…"
            VoiceTraceLog.append(kind: .status, text: "麦克风已开启")
            speech.start()
        }
    }

    @objc private func captureTapped() {
        captureButton.isEnabled = false
        statusLabel.text = "拍照中…"
        camera.capturePhoto { [weak self] data, err in
            guard let self = self else { return }
            if let err = err {
                self.captureButton.isEnabled = true
                self.statusLabel.text = "拍失败了，再试一次"
                VoiceTraceLog.append(kind: .error, text: err)
                return
            }
            guard let data = data else {
                self.captureButton.isEnabled = true
                return
            }
            let record = ReadingPhotoStore.save(jpeg: data)
            self.captureButton.isEnabled = true
            self.onPhotoCaptured?(record.id)
            self.uploadPhotoIfConnected(recordId: record.id, jpeg: data)
        }
    }

    private func uploadPhotoIfConnected(recordId: String, jpeg: Data) {
        guard ParticipantStore.lastHeartbeatOk, !ParticipantStore.participantId.isEmpty else {
            ReadingPhotoStore.update(id: recordId, uploadState: .none)
            onPhotoUploadChanged?()
            return
        }
        uploadPhoto(recordId: recordId, jpeg: jpeg)
    }

    private func uploadPhoto(recordId: String, jpeg: Data) {
        ReadingPhotoStore.update(id: recordId, uploadState: .uploading)
        onPhotoUploadChanged?()
        BrainAPI.uploadPhoto(intentURL: ParticipantStore.brainIntentURL, jpegData: jpeg) { [weak self] upload in
            switch upload {
            case .failure:
                ReadingPhotoStore.update(id: recordId, uploadState: .failed)
            case .success(let assetId):
                ReadingPhotoStore.update(id: recordId, uploadState: .uploaded, assetId: assetId)
            }
            self?.onPhotoUploadChanged?()
        }
    }

    private func sendVoiceIntent(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard ParticipantStore.lastHeartbeatOk else {
            statusLabel.text = "连不上，请找家长"
            return
        }
        let pid = ParticipantStore.participantId
        guard !pid.isEmpty else { return }
        statusLabel.text = "正在发送…"
        BrainAPI.postIntent(intentURL: ParticipantStore.brainIntentURL, text: trimmed, participantId: pid) { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure:
                self.statusLabel.text = "没听清，再说一次"
            case .success:
                self.statusLabel.text = "听到了 ✓"
                if self.micEnabled {
                    self.scheduleMicRestart()
                }
            }
        }
    }

    private func scheduleMicRestart() {
        restartWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.micEnabled else { return }
            self.speech.start()
            self.micButton.setTitle("正在听", for: .normal)
            self.statusLabel.text = "说吧…"
        }
        restartWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8, execute: work)
    }

    private func showAlert(_ message: String) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }
}

extension ReadingCaptureViewController: ReadingSpeechServiceDelegate {
    func speechService(_ service: ReadingSpeechService, didUpdatePartial text: String) {
        if !text.isEmpty {
            VoiceTraceLog.append(kind: .partial, text: text)
        }
    }

    func speechService(_ service: ReadingSpeechService, didFinalize text: String) {
        if !text.isEmpty {
            VoiceTraceLog.append(kind: .final, text: text)
        }
        if micEnabled {
            sendVoiceIntent(text)
        }
    }

    func speechService(_ service: ReadingSpeechService, didUpdateStatus text: String) {
        if micEnabled && !text.isEmpty {
            statusLabel.text = "说吧…"
        }
    }

    func speechService(_ service: ReadingSpeechService, didFail message: String) {
        statusLabel.text = "请再说一次"
    }

    func speechService(_ service: ReadingSpeechService, didUpdateLevel level: Float) {
        if micEnabled {
            micButton.alpha = CGFloat(0.85 + min(0.15, level * 0.3))
        }
    }
}
