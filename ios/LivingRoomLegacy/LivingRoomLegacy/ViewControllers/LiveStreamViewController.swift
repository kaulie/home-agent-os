import UIKit

final class LiveStreamViewController: UIViewController {
    var onStreamActive: ((Bool) -> Void)?

    private let controller = LegacyLiveStreamController()
    private let previewView = UIView()
    private let statusLabel = UILabel()
    private let detailLabel = UILabel()
    private let startButton = UIButton(type: .system)
    private let stopButton = UIButton(type: .system)
    private var previewStarted = false
    private var durationTimer: Timer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        controller.onPhaseChanged = { [weak self] phase in
            self?.updateUI(for: phase)
        }
        setupUI()
    }

    func beginSessionIfNeeded() {
        guard !previewStarted else {
            controller.capture.attachPreview(to: previewView)
            return
        }
        statusLabel.text = "正在打开相机…"
        controller.startPreview { [weak self] ok, message in
            guard let self else { return }
            if ok {
                self.previewStarted = true
                self.controller.capture.attachPreview(to: self.previewView)
                self.statusLabel.text = "○ OFF"
            } else {
                self.statusLabel.text = message.isEmpty ? "相机打不开" : message
            }
        }
    }

    func endSession() {
        durationTimer?.invalidate()
        durationTimer = nil
        if controller.phase == .streaming || controller.phase == .starting {
            controller.stopStream(keepPreview: false, completion: nil)
        } else {
            controller.stopPreview()
        }
        previewStarted = false
        setKeepScreenAwake(false)
        onStreamActive?(false)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        controller.capture.layoutPreview(in: previewView)
    }

    private func setupUI() {
        previewView.backgroundColor = UIColor(white: 0.12, alpha: 1)
        previewView.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = LegacyTheme.fontTitle
        statusLabel.textColor = .white
        statusLabel.textAlignment = .center
        statusLabel.text = "○ OFF"
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        detailLabel.font = LegacyTheme.fontHint
        detailLabel.textColor = UIColor(white: 0.9, alpha: 1)
        detailLabel.textAlignment = .center
        detailLabel.numberOfLines = 3
        detailLabel.text = "640×480 · 仅视频"
        detailLabel.translatesAutoresizingMaskIntoConstraints = false

        LegacyUI.styleKidPrimaryButton(startButton, title: "Start Stream")
        startButton.addTarget(self, action: #selector(startTapped), for: .touchUpInside)
        startButton.translatesAutoresizingMaskIntoConstraints = false

        stopButton.setTitle("Stop Stream", for: .normal)
        stopButton.setTitleColor(.white, for: .normal)
        stopButton.titleLabel?.font = LegacyTheme.fontButton
        stopButton.backgroundColor = LegacyTheme.danger
        stopButton.layer.cornerRadius = 14
        stopButton.contentEdgeInsets = UIEdgeInsets(top: 14, left: 20, bottom: 14, right: 20)
        stopButton.addTarget(self, action: #selector(stopTapped), for: .touchUpInside)
        stopButton.isHidden = true
        stopButton.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(previewView)
        view.addSubview(statusLabel)
        view.addSubview(detailLabel)
        view.addSubview(startButton)
        view.addSubview(stopButton)

        NSLayoutConstraint.activate([
            previewView.topAnchor.constraint(equalTo: view.topAnchor),
            previewView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            previewView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            previewView.bottomAnchor.constraint(equalTo: startButton.topAnchor, constant: -20),

            statusLabel.topAnchor.constraint(equalTo: previewView.topAnchor, constant: 16),
            statusLabel.leadingAnchor.constraint(equalTo: previewView.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: previewView.trailingAnchor, constant: -16),

            detailLabel.bottomAnchor.constraint(equalTo: previewView.bottomAnchor, constant: -16),
            detailLabel.leadingAnchor.constraint(equalTo: previewView.leadingAnchor, constant: 16),
            detailLabel.trailingAnchor.constraint(equalTo: previewView.trailingAnchor, constant: -16),

            startButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            startButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -20),
            startButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 180),

            stopButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            stopButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -20),
            stopButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 180),
        ])
    }

    @objc private func startTapped() {
        let ingest = ParticipantStore.macIngestConnectURL
        statusLabel.text = "正在连接 Mac…"
        startButton.isEnabled = false
        controller.startStream(ingestBaseURL: ingest, includeAudio: false) { [weak self] err in
            guard let self else { return }
            self.startButton.isEnabled = true
            if let err {
                self.statusLabel.text = "ERROR"
                self.detailLabel.text = err.localizedDescription
            }
        }
    }

    @objc private func stopTapped() {
        stopButton.isEnabled = false
        controller.stopStream(keepPreview: true) { [weak self] in
            guard let self else { return }
            self.stopButton.isEnabled = true
            self.onStreamActive?(false)
        }
    }

    private func updateUI(for phase: LegacyLiveStreamController.Phase) {
        switch phase {
        case .idle:
            statusLabel.text = "○ OFF"
            detailLabel.text = "640×480 · 仅视频"
            startButton.isHidden = false
            stopButton.isHidden = true
            durationTimer?.invalidate()
            durationTimer = nil
            setKeepScreenAwake(false)
            onStreamActive?(false)
        case .starting:
            statusLabel.text = "STARTING"
            startButton.isHidden = true
            stopButton.isHidden = true
            setKeepScreenAwake(true)
        case .streaming:
            statusLabel.text = "● LIVE"
            detailLabel.text = "\(controller.streamId)\n\(controller.connectedHost)"
            startButton.isHidden = true
            stopButton.isHidden = false
            setKeepScreenAwake(true)
            onStreamActive?(true)
            startDurationTimer()
        case .stopping:
            statusLabel.text = "STOPPING"
            startButton.isHidden = true
            stopButton.isHidden = true
            setKeepScreenAwake(true)
        case .error:
            statusLabel.text = "ERROR"
            detailLabel.text = controller.errorMessage
            startButton.isHidden = false
            stopButton.isHidden = true
            durationTimer?.invalidate()
            durationTimer = nil
            setKeepScreenAwake(false)
            onStreamActive?(false)
        }
    }

    private func setKeepScreenAwake(_ awake: Bool) {
        UIApplication.shared.isIdleTimerDisabled = awake
    }

    private func startDurationTimer() {
        durationTimer?.invalidate()
        let started = Date()
        durationTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self, self.controller.phase == .streaming else { return }
            let sec = max(0, Int(Date().timeIntervalSince(started)))
            let m = sec / 60
            let s = sec % 60
            self.detailLabel.text = "\(self.controller.streamId)\n\(self.controller.connectedHost)\n\(String(format: "%02d:%02d", m, s))"
        }
        if let timer = durationTimer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }
}
