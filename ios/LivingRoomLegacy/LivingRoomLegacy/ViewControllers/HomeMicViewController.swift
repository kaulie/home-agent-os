import UIKit

/// Legacy「拾音」页：大话筒 + 电平，绑定 `HomeMicController`（服务层在 Services/HomeMic）。
final class HomeMicViewController: UIViewController {
    var onListeningActive: ((Bool) -> Void)?

    private let controller = HomeMicController()
    private let connectionPill = UILabel()
    private let headlineLabel = UILabel()
    private let hearingBadge = UILabel()
    private let hintLabel = UILabel()
    private let errorBanner = UILabel()
    private let micButton = UIButton(type: .system)
    private let micCircle = UIView()
    private let pulseRing = UIView()
    private let levelBars = HomeMicLevelBarsView()
    private var pulseAnimator: UIViewPropertyAnimator?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.06, green: 0.07, blue: 0.10, alpha: 1)
        wireController()
        setupUI()
        refreshUI()
    }

    func beginSessionIfNeeded() {
        controller.connectIfNeeded()
        refreshUI()
    }

    func endSession() {
        controller.disconnect()
        setKeepScreenAwake(false)
        onListeningActive?(false)
        refreshUI()
    }

    private func wireController() {
        controller.onAudioLevel = { [weak self] level in
            self?.levelBars.level = level
            self?.refreshHearingBadge(level: level)
        }
        controller.onStatusChange = { [weak self] _ in
            self?.refreshUI()
        }
        controller.onConnectionStateChange = { [weak self] _ in
            self?.refreshUI()
        }
    }

    private func setupUI() {
        connectionPill.font = LegacyTheme.fontHint
        connectionPill.textColor = LegacyTheme.textSecondary
        connectionPill.textAlignment = .center
        connectionPill.backgroundColor = UIColor(white: 1, alpha: 0.08)
        connectionPill.layer.cornerRadius = 14
        connectionPill.translatesAutoresizingMaskIntoConstraints = false

        headlineLabel.font = UIFont.systemFont(ofSize: 36, weight: .bold)
        headlineLabel.textColor = UIColor(white: 0.78, alpha: 1)
        headlineLabel.textAlignment = .center
        headlineLabel.translatesAutoresizingMaskIntoConstraints = false

        hearingBadge.font = UIFont.systemFont(ofSize: 16, weight: .semibold)
        hearingBadge.textColor = .white
        hearingBadge.textAlignment = .center
        hearingBadge.layer.cornerRadius = 16
        hearingBadge.clipsToBounds = true
        hearingBadge.isHidden = true
        hearingBadge.translatesAutoresizingMaskIntoConstraints = false

        hintLabel.font = LegacyTheme.fontHint
        hintLabel.textColor = LegacyTheme.textSecondary
        hintLabel.textAlignment = .center
        hintLabel.numberOfLines = 0
        hintLabel.translatesAutoresizingMaskIntoConstraints = false

        errorBanner.font = UIFont.systemFont(ofSize: 16, weight: .semibold)
        errorBanner.textColor = .white
        errorBanner.textAlignment = .center
        errorBanner.numberOfLines = 0
        errorBanner.backgroundColor = UIColor(red: 1, green: 0.55, blue: 0.1, alpha: 0.22)
        errorBanner.layer.cornerRadius = 12
        errorBanner.layer.borderWidth = 1
        errorBanner.layer.borderColor = UIColor(red: 1, green: 0.55, blue: 0.1, alpha: 0.45).cgColor
        errorBanner.isHidden = true
        errorBanner.translatesAutoresizingMaskIntoConstraints = false

        pulseRing.layer.borderWidth = 2
        pulseRing.layer.borderColor = UIColor.red.withAlphaComponent(0.45).cgColor
        pulseRing.isUserInteractionEnabled = false
        pulseRing.translatesAutoresizingMaskIntoConstraints = false

        micCircle.layer.cornerRadius = 80
        micCircle.isUserInteractionEnabled = false
        micCircle.translatesAutoresizingMaskIntoConstraints = false

        if let micImage = ChatIcons.microphone(diameter: 64, color: .white) {
            micButton.setImage(micImage, for: .normal)
        } else {
            micButton.setTitle("🎤", for: .normal)
            micButton.titleLabel?.font = UIFont.systemFont(ofSize: 52)
        }
        micButton.tintColor = .white
        micButton.addTarget(self, action: #selector(micTapped), for: .touchUpInside)
        micButton.translatesAutoresizingMaskIntoConstraints = false

        levelBars.translatesAutoresizingMaskIntoConstraints = false
        levelBars.isHidden = true

        view.addSubview(connectionPill)
        view.addSubview(errorBanner)
        view.addSubview(headlineLabel)
        view.addSubview(pulseRing)
        view.addSubview(micCircle)
        view.addSubview(micButton)
        view.addSubview(levelBars)
        view.addSubview(hearingBadge)
        view.addSubview(hintLabel)

        NSLayoutConstraint.activate([
            connectionPill.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            connectionPill.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            connectionPill.heightAnchor.constraint(equalToConstant: 32),
            connectionPill.widthAnchor.constraint(greaterThanOrEqualToConstant: 120),

            errorBanner.topAnchor.constraint(equalTo: connectionPill.bottomAnchor, constant: 12),
            errorBanner.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            errorBanner.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            micButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            micButton.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -20),
            micButton.widthAnchor.constraint(equalToConstant: 160),
            micButton.heightAnchor.constraint(equalToConstant: 160),

            micCircle.centerXAnchor.constraint(equalTo: micButton.centerXAnchor),
            micCircle.centerYAnchor.constraint(equalTo: micButton.centerYAnchor),
            micCircle.widthAnchor.constraint(equalToConstant: 160),
            micCircle.heightAnchor.constraint(equalToConstant: 160),

            pulseRing.centerXAnchor.constraint(equalTo: micButton.centerXAnchor),
            pulseRing.centerYAnchor.constraint(equalTo: micButton.centerYAnchor),
            pulseRing.widthAnchor.constraint(equalToConstant: 190),
            pulseRing.heightAnchor.constraint(equalToConstant: 190),

            headlineLabel.topAnchor.constraint(equalTo: micButton.bottomAnchor, constant: 24),
            headlineLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            headlineLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            levelBars.topAnchor.constraint(equalTo: headlineLabel.bottomAnchor, constant: 16),
            levelBars.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            levelBars.widthAnchor.constraint(equalToConstant: 200),
            levelBars.heightAnchor.constraint(equalToConstant: 56),

            hearingBadge.topAnchor.constraint(equalTo: levelBars.bottomAnchor, constant: 12),
            hearingBadge.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            hearingBadge.heightAnchor.constraint(equalToConstant: 32),
            hearingBadge.widthAnchor.constraint(greaterThanOrEqualToConstant: 120),

            hintLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            hintLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            hintLabel.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
        ])
    }

    @objc private func micTapped() {
        if controller.isListening {
            controller.stopListening()
            setKeepScreenAwake(false)
        } else {
            controller.startListening()
            setKeepScreenAwake(true)
        }
        onListeningActive?(controller.isListening)
        refreshUI()
    }

    private func refreshUI() {
        let listening = controller.isListening
        let connected = controller.connectionState == .connected

        connectionPill.text = "  \(connectionLabel())  "
        headlineLabel.text = listening ? (connected ? "正在听" : "准备听") : "话筒已关"
        headlineLabel.textColor = listening ? UIColor(red: 1, green: 0.28, blue: 0.32, alpha: 1) : UIColor(white: 0.78, alpha: 1)

        hintLabel.text = listening
            ? (connected ? "对着话筒说话，看电平条会不会跳" : "正在连接 Mac 拾音服务…")
            : "点一下大按钮，开始拾音"

        levelBars.isHidden = !listening
        hearingBadge.isHidden = !listening
        pulseRing.isHidden = !listening
        pulseRing.layer.cornerRadius = 95

        if listening {
            micCircle.backgroundColor = UIColor(red: 0.88, green: 0.15, blue: 0.2, alpha: 1)
            startPulse()
        } else {
            micCircle.backgroundColor = UIColor(white: 0.28, alpha: 1)
            stopPulse()
            levelBars.level = 0
        }

        if case .failed(let msg) = controller.connectionState, !msg.isEmpty {
            errorBanner.text = msg
            errorBanner.isHidden = false
        } else if listening, controller.connectionState != .connected {
            errorBanner.text = "暂时连不上拾音服务（:\(HomeMicSettings.port)）"
            errorBanner.isHidden = false
        } else {
            errorBanner.isHidden = true
        }

        onListeningActive?(listening)
    }

    private func refreshHearingBadge(level: Float) {
        guard controller.isListening else { return }
        if level > 0.06 {
            hearingBadge.text = "  能听到你说话  "
            hearingBadge.backgroundColor = LegacyTheme.success.withAlphaComponent(0.85)
        } else {
            hearingBadge.text = "  正在听，请说话  "
            hearingBadge.backgroundColor = UIColor(red: 0.88, green: 0.15, blue: 0.2, alpha: 0.85)
        }
    }

    private func connectionLabel() -> String {
        switch controller.connectionState {
        case .connected: return "已就绪"
        case .connecting: return "正在连接…"
        case .disconnected: return "未连接"
        case .failed: return "连不上"
        }
    }

    private func startPulse() {
        stopPulse()
        pulseRing.transform = .identity
        pulseRing.alpha = 0.75
        pulseAnimator = UIViewPropertyAnimator(duration: 1.1, curve: .easeInOut) { [weak self] in
            self?.pulseRing.transform = CGAffineTransform(scaleX: 1.08, y: 1.08)
            self?.pulseRing.alpha = 0.35
        }
        pulseAnimator?.addAnimations({ [weak self] in
            self?.pulseRing.transform = .identity
            self?.pulseRing.alpha = 0.75
        }, delayFactor: 0.5)
        pulseAnimator?.addCompletion { [weak self] _ in
            guard let self, self.controller.isListening else { return }
            self.startPulse()
        }
        pulseAnimator?.startAnimation()
    }

    private func stopPulse() {
        pulseAnimator?.stopAnimation(true)
        pulseAnimator = nil
        pulseRing.transform = .identity
        pulseRing.alpha = 1
    }

    private func setKeepScreenAwake(_ awake: Bool) {
        UIApplication.shared.isIdleTimerDisabled = awake
    }
}

private final class HomeMicLevelBarsView: UIView {
    var level: Float = 0 {
        didSet { setNeedsDisplay() }
    }

    private let barCount = 12

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isUserInteractionEnabled = false
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        let spacing: CGFloat = 6
        let barWidth = (rect.width - spacing * CGFloat(barCount - 1)) / CGFloat(barCount)
        for index in 0 ..< barCount {
            let threshold = Float(index + 1) / Float(barCount)
            let active = level >= threshold * 0.65
            let base: CGFloat = active ? 12 + CGFloat(level) * 44 : 8
            let height = min(rect.height, base)
            let x = CGFloat(index) * (barWidth + spacing)
            let y = rect.height - height
            let path = UIBezierPath(roundedRect: CGRect(x: x, y: y, width: barWidth, height: height), cornerRadius: 3)
            barColor(for: index).setFill()
            path.fill()
        }
        _ = ctx
    }

    private func barColor(for index: Int) -> UIColor {
        let threshold = Float(index + 1) / Float(barCount)
        if level < threshold * 0.5 { return UIColor.white.withAlphaComponent(0.18) }
        if index >= barCount - 3 { return UIColor.red }
        if index >= barCount - 6 { return UIColor.orange }
        return LegacyTheme.success
    }
}
