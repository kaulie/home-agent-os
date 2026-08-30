import UIKit

/// 拾音主屏：大话筒 + 电平 + 友好唤醒引导。
final class HomeMicViewController: UIViewController {
    private let controller = HomeMicController()

    private let ambientGlow = UIView()
    private let connectionPill = UILabel()
    private let tipCard = UIView()
    private let tipEyebrow = UILabel()
    private let tipBody = UILabel()
    private let stepRow = UIStackView()
    private let headlineLabel = UILabel()
    private let hearingBadge = UILabel()
    private let hintLabel = UILabel()
    private let errorBanner = UILabel()
    private let micButton = UIButton(type: .system)
    private let micCircle = UIView()
    private let pulseRing = UIView()
    private let levelBars = HomeMicLevelBarsView()
    private var pulseTimer: Timer?

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "拾音"
        view.backgroundColor = PickupTheme.canvas
        navigationItem.rightBarButtonItem = UIBarButtonItem(
            title: "设置",
            style: .plain,
            target: self,
            action: #selector(openSettings)
        )
        wireController()
        setupUI()
        refreshUI(animated: false)
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        controller.connectIfNeeded()
        refreshUI(animated: false)
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if isMovingFromParent || isBeingDismissed {
            controller.disconnect()
            setKeepScreenAwake(false)
        }
    }

    @objc private func openSettings() {
        let settings = SettingsViewController()
        settings.onSaved = { [weak self] in
            self?.controller.disconnect()
            self?.controller.connectIfNeeded()
            self?.refreshUI(animated: true)
        }
        navigationController?.pushViewController(settings, animated: true)
    }

    private func wireController() {
        controller.onAudioLevel = { [weak self] level in
            self?.levelBars.level = level
            self?.refreshHearingBadge(level: level)
        }
        controller.onStatusChange = { [weak self] _ in
            self?.refreshUI(animated: true)
        }
        controller.onConnectionStateChange = { [weak self] _ in
            self?.refreshUI(animated: true)
        }
    }

    private func setupUI() {
        ambientGlow.backgroundColor = PickupTheme.accent.withAlphaComponent(0.10)
        ambientGlow.isUserInteractionEnabled = false
        ambientGlow.translatesAutoresizingMaskIntoConstraints = false
        ambientGlow.layer.cornerRadius = 140

        connectionPill.font = UIFont.systemFont(ofSize: 14, weight: .semibold)
        connectionPill.textColor = PickupTheme.textSecondary
        connectionPill.textAlignment = .center
        connectionPill.backgroundColor = UIColor(white: 1, alpha: 0.07)
        connectionPill.layer.cornerRadius = 14
        connectionPill.clipsToBounds = true
        connectionPill.translatesAutoresizingMaskIntoConstraints = false

        tipCard.backgroundColor = PickupTheme.accentSoft
        tipCard.layer.cornerRadius = 18
        tipCard.layer.borderWidth = 1
        tipCard.layer.borderColor = PickupTheme.accent.withAlphaComponent(0.35).cgColor
        tipCard.translatesAutoresizingMaskIntoConstraints = false

        tipEyebrow.font = UIFont.systemFont(ofSize: 12, weight: .bold)
        tipEyebrow.textColor = PickupTheme.accent
        tipEyebrow.textAlignment = .left
        tipEyebrow.translatesAutoresizingMaskIntoConstraints = false

        tipBody.numberOfLines = 0
        tipBody.textAlignment = .left
        tipBody.translatesAutoresizingMaskIntoConstraints = false

        stepRow.axis = .horizontal
        stepRow.spacing = 8
        stepRow.distribution = .fillEqually
        stepRow.translatesAutoresizingMaskIntoConstraints = false

        headlineLabel.font = PickupTheme.fontDisplay
        headlineLabel.textColor = PickupTheme.textPrimary
        headlineLabel.textAlignment = .center
        headlineLabel.translatesAutoresizingMaskIntoConstraints = false

        hearingBadge.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
        hearingBadge.textColor = .white
        hearingBadge.textAlignment = .center
        hearingBadge.layer.cornerRadius = 16
        hearingBadge.clipsToBounds = true
        hearingBadge.isHidden = true
        hearingBadge.translatesAutoresizingMaskIntoConstraints = false

        hintLabel.font = PickupTheme.fontHint
        hintLabel.textColor = PickupTheme.textMuted
        hintLabel.textAlignment = .center
        hintLabel.numberOfLines = 0
        hintLabel.translatesAutoresizingMaskIntoConstraints = false

        errorBanner.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
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
        pulseRing.layer.borderColor = PickupTheme.micLive.withAlphaComponent(0.45).cgColor
        pulseRing.isUserInteractionEnabled = false
        pulseRing.translatesAutoresizingMaskIntoConstraints = false

        micCircle.layer.cornerRadius = 59
        micCircle.isUserInteractionEnabled = false
        micCircle.translatesAutoresizingMaskIntoConstraints = false

        if let micImage = PickupIcons.microphone(diameter: 48, color: .white) {
            micButton.setImage(micImage, for: .normal)
        } else {
            micButton.setTitle("Mic", for: .normal)
            micButton.titleLabel?.font = UIFont.systemFont(ofSize: 28, weight: .bold)
        }
        micButton.tintColor = .white
        micButton.addTarget(self, action: #selector(micTapped), for: .touchUpInside)
        micButton.translatesAutoresizingMaskIntoConstraints = false
        micButton.accessibilityLabel = "开关话筒"

        levelBars.translatesAutoresizingMaskIntoConstraints = false
        levelBars.isHidden = true

        tipCard.addSubview(tipEyebrow)
        tipCard.addSubview(tipBody)
        tipCard.addSubview(stepRow)

        view.addSubview(ambientGlow)
        view.addSubview(connectionPill)
        view.addSubview(errorBanner)
        view.addSubview(tipCard)
        view.addSubview(pulseRing)
        view.addSubview(micCircle)
        view.addSubview(micButton)
        view.addSubview(headlineLabel)
        view.addSubview(levelBars)
        view.addSubview(hearingBadge)
        view.addSubview(hintLabel)

        NSLayoutConstraint.activate([
            ambientGlow.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            ambientGlow.centerYAnchor.constraint(equalTo: micButton.centerYAnchor),
            ambientGlow.widthAnchor.constraint(equalToConstant: 200),
            ambientGlow.heightAnchor.constraint(equalToConstant: 200),

            connectionPill.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 10),
            connectionPill.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            connectionPill.heightAnchor.constraint(equalToConstant: 28),
            connectionPill.widthAnchor.constraint(greaterThanOrEqualToConstant: 110),

            errorBanner.topAnchor.constraint(equalTo: connectionPill.bottomAnchor, constant: 10),
            errorBanner.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            errorBanner.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            tipCard.topAnchor.constraint(equalTo: connectionPill.bottomAnchor, constant: 12),
            tipCard.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            tipCard.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            tipEyebrow.topAnchor.constraint(equalTo: tipCard.topAnchor, constant: 12),
            tipEyebrow.leadingAnchor.constraint(equalTo: tipCard.leadingAnchor, constant: 14),
            tipEyebrow.trailingAnchor.constraint(equalTo: tipCard.trailingAnchor, constant: -14),

            tipBody.topAnchor.constraint(equalTo: tipEyebrow.bottomAnchor, constant: 4),
            tipBody.leadingAnchor.constraint(equalTo: tipCard.leadingAnchor, constant: 14),
            tipBody.trailingAnchor.constraint(equalTo: tipCard.trailingAnchor, constant: -14),

            stepRow.topAnchor.constraint(equalTo: tipBody.bottomAnchor, constant: 10),
            stepRow.leadingAnchor.constraint(equalTo: tipCard.leadingAnchor, constant: 12),
            stepRow.trailingAnchor.constraint(equalTo: tipCard.trailingAnchor, constant: -12),
            stepRow.bottomAnchor.constraint(equalTo: tipCard.bottomAnchor, constant: -12),
            stepRow.heightAnchor.constraint(equalToConstant: 28),

            micButton.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            micButton.topAnchor.constraint(equalTo: tipCard.bottomAnchor, constant: 44),
            micButton.widthAnchor.constraint(equalToConstant: 118),
            micButton.heightAnchor.constraint(equalToConstant: 118),

            micCircle.centerXAnchor.constraint(equalTo: micButton.centerXAnchor),
            micCircle.centerYAnchor.constraint(equalTo: micButton.centerYAnchor),
            micCircle.widthAnchor.constraint(equalToConstant: 118),
            micCircle.heightAnchor.constraint(equalToConstant: 118),

            pulseRing.centerXAnchor.constraint(equalTo: micButton.centerXAnchor),
            pulseRing.centerYAnchor.constraint(equalTo: micButton.centerYAnchor),
            pulseRing.widthAnchor.constraint(equalToConstant: 140),
            pulseRing.heightAnchor.constraint(equalToConstant: 140),

            headlineLabel.topAnchor.constraint(equalTo: micButton.bottomAnchor, constant: 14),
            headlineLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            headlineLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),

            levelBars.topAnchor.constraint(equalTo: headlineLabel.bottomAnchor, constant: 10),
            levelBars.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            levelBars.widthAnchor.constraint(equalToConstant: 180),
            levelBars.heightAnchor.constraint(equalToConstant: 40),

            hearingBadge.topAnchor.constraint(equalTo: levelBars.bottomAnchor, constant: 8),
            hearingBadge.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            hearingBadge.heightAnchor.constraint(equalToConstant: 28),
            hearingBadge.widthAnchor.constraint(greaterThanOrEqualToConstant: 110),

            hintLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 28),
            hintLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -28),
            hintLabel.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -14),
        ])

        rebuildSteps(PickupCopy.stepsIdle, activeIndex: 0)
    }

    private func rebuildSteps(_ titles: [String], activeIndex: Int) {
        stepRow.arrangedSubviews.forEach {
            stepRow.removeArrangedSubview($0)
            $0.removeFromSuperview()
        }
        for (index, title) in titles.enumerated() {
            let chip = UILabel()
            chip.text = title
            chip.textAlignment = .center
            chip.font = UIFont.systemFont(ofSize: 12, weight: .semibold)
            chip.layer.cornerRadius = 10
            chip.clipsToBounds = true
            if index == activeIndex {
                chip.textColor = UIColor(red: 0.18, green: 0.10, blue: 0.04, alpha: 1)
                chip.backgroundColor = PickupTheme.accent
            } else {
                chip.textColor = PickupTheme.textSecondary
                chip.backgroundColor = UIColor(white: 1, alpha: 0.06)
            }
            stepRow.addArrangedSubview(chip)
        }
    }

    @objc private func micTapped() {
        if controller.isListening {
            controller.stopListening()
            setKeepScreenAwake(false)
        } else {
            controller.startListening()
            setKeepScreenAwake(true)
        }
        refreshUI(animated: true)
    }

    private func refreshUI(animated: Bool) {
        let listening = controller.isListening
        let connected = controller.connectionState == .connected

        let apply = {
            self.connectionPill.text = "  \(self.connectionLabel())  "
            self.tipEyebrow.text = PickupCopy.tipTitle(listening: listening).uppercased()
            self.tipBody.attributedText = PickupCopy.tipAttributed(listening: listening)
            self.rebuildSteps(
                listening ? PickupCopy.stepsListening : PickupCopy.stepsIdle,
                activeIndex: listening ? (connected ? 1 : 0) : 0
            )

            self.headlineLabel.text = listening
                ? PickupCopy.listeningHeadline(connected: connected)
                : PickupCopy.idleHeadline()
            self.headlineLabel.textColor = listening ? PickupTheme.micLive : PickupTheme.textPrimary

            self.hintLabel.text = PickupCopy.footerHint(listening: listening, connected: connected)

            self.levelBars.isHidden = !listening
            self.hearingBadge.isHidden = !listening
            self.pulseRing.isHidden = !listening
            self.pulseRing.layer.cornerRadius = 70

            self.ambientGlow.backgroundColor = listening
                ? PickupTheme.micLive.withAlphaComponent(0.14)
                : PickupTheme.accent.withAlphaComponent(0.10)
            self.view.backgroundColor = listening ? PickupTheme.canvasWarm : PickupTheme.canvas

            if listening {
                self.micCircle.backgroundColor = PickupTheme.micLive
                self.startPulse()
            } else {
                self.micCircle.backgroundColor = PickupTheme.micIdle
                self.stopPulse()
                self.levelBars.level = 0
            }

            if case .failed(let msg) = self.controller.connectionState, !msg.isEmpty {
                self.errorBanner.text = msg
                self.errorBanner.isHidden = false
            } else if listening, self.controller.connectionState != .connected {
                self.errorBanner.text = "暂时连不上客厅拾音（:\(HomeMicSettings.port)）"
                self.errorBanner.isHidden = false
            } else {
                self.errorBanner.isHidden = true
            }
        }

        if animated {
            UIView.transition(with: tipCard, duration: 0.25, options: .transitionCrossDissolve, animations: apply)
        } else {
            apply()
        }
    }

    private func refreshHearingBadge(level: Float) {
        guard controller.isListening else { return }
        let pct = Int((max(0, min(1, level)) * 100).rounded())
        if level > 0.06 {
            hearingBadge.text = "  能听到 · \(pct)%  "
            hearingBadge.backgroundColor = PickupTheme.success.withAlphaComponent(0.88)
            if stepRow.arrangedSubviews.count == 3 {
                rebuildSteps(PickupCopy.stepsListening, activeIndex: 1)
            }
        } else {
            hearingBadge.text = "  正在听 · \(pct)%  "
            hearingBadge.backgroundColor = PickupTheme.micLive.withAlphaComponent(0.85)
        }
    }

    private func connectionLabel() -> String {
        switch controller.connectionState {
        case .connected: return "客厅已连上"
        case .connecting: return "正在连接…"
        case .disconnected: return "未连接"
        case .failed: return "连不上"
        }
    }

    private func startPulse() {
        stopPulse()
        pulseRing.transform = .identity
        pulseRing.alpha = 0.75
        // UIViewPropertyAnimator recursive completion is unstable on iOS 12.
        let timer = Timer(timeInterval: 1.1, repeats: true) { [weak self] _ in
            guard let self = self, self.controller.isListening else { return }
            UIView.animate(
                withDuration: 0.55,
                delay: 0,
                options: [.curveEaseInOut, .allowUserInteraction, .beginFromCurrentState],
                animations: {
                    self.pulseRing.transform = CGAffineTransform(scaleX: 1.08, y: 1.08)
                    self.pulseRing.alpha = 0.35
                },
                completion: { [weak self] finished in
                    guard finished, let self = self, self.controller.isListening else { return }
                    UIView.animate(
                        withDuration: 0.55,
                        delay: 0,
                        options: [.curveEaseInOut, .allowUserInteraction, .beginFromCurrentState],
                        animations: {
                            self.pulseRing.transform = .identity
                            self.pulseRing.alpha = 0.75
                        }
                    )
                }
            )
        }
        pulseTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    private func stopPulse() {
        pulseTimer?.invalidate()
        pulseTimer = nil
        pulseRing.layer.removeAllAnimations()
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
    }

    private func barColor(for index: Int) -> UIColor {
        let threshold = Float(index + 1) / Float(barCount)
        if level < threshold * 0.5 { return UIColor.white.withAlphaComponent(0.18) }
        if index >= barCount - 3 { return UIColor.red }
        if index >= barCount - 6 { return PickupTheme.accent }
        return PickupTheme.success
    }
}
