import UIKit

final class SettingsViewController: UIViewController {
    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let statusLabel = UILabel()
    private let networkHintLabel = UILabel()
    private let networkSegment = PillSegmentControl(titles: ["家里", "外面"])
    private let reconnectButton = UIButton(type: .system)
    private let advancedToggle = UIButton(type: .system)
    private let advancedStack = UIStackView()
    private let macIngestField = UITextField()
    private let homeMicHostField = UITextField()
    private let homeMicPortField = UITextField()
    private let homeMicEnergySwitch = UISwitch()
    private let participantLabel = LegacyUI.monoLabel(0)
    private let heartbeatHistoryLabel = LegacyUI.monoLabel(0)
    private var countdownTimer: Timer?
    private var advancedVisible = false
    private var suppressSegmentCallback = false

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "家长"
        view.backgroundColor = LegacyTheme.background
        setupUI()
        refreshValues()
    }

    private func setupUI() {
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.alwaysBounceVertical = true
        view.addSubview(scrollView)
        NSLayoutConstraint.activate([
            scrollView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        stack.axis = .vertical
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: scrollView.topAnchor, constant: 20),
            stack.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -20),
            stack.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -24),
            stack.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -40),
        ])

        let card = LegacyUI.cardView()
        card.translatesAutoresizingMaskIntoConstraints = false
        let cardStack = UIStackView()
        cardStack.axis = .vertical
        cardStack.spacing = 16
        cardStack.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = LegacyTheme.fontTitle
        statusLabel.textAlignment = .center
        statusLabel.numberOfLines = 0

        networkHintLabel.font = LegacyTheme.fontHint
        networkHintLabel.textColor = LegacyTheme.textSecondary
        networkHintLabel.textAlignment = .center
        networkHintLabel.numberOfLines = 0
        networkHintLabel.text = "连哪个网络？点一下就行"

        networkSegment.onSelectionChanged = { [weak self] index in
            guard let self = self, !self.suppressSegmentCallback else { return }
            guard let endpoint = BrainEndpoint(rawValue: index) else { return }
            ConnectionManager.shared.switchToEndpoint(endpoint)
            self.refreshValues()
        }

        LegacyUI.styleKidPrimaryButton(reconnectButton, title: "重新连接")
        reconnectButton.addTarget(self, action: #selector(reconnect), for: .touchUpInside)

        cardStack.addArrangedSubview(statusLabel)
        cardStack.addArrangedSubview(networkHintLabel)
        cardStack.addArrangedSubview(networkSegment)
        cardStack.addArrangedSubview(reconnectButton)
        card.addSubview(cardStack)
        NSLayoutConstraint.activate([
            cardStack.topAnchor.constraint(equalTo: card.topAnchor, constant: 20),
            cardStack.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 16),
            cardStack.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -16),
            cardStack.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -20),
        ])
        stack.addArrangedSubview(card)

        advancedToggle.setTitle("更多 ▼", for: .normal)
        advancedToggle.setTitleColor(LegacyTheme.textSecondary, for: .normal)
        advancedToggle.titleLabel?.font = UIFont.systemFont(ofSize: 15)
        advancedToggle.addTarget(self, action: #selector(toggleAdvanced), for: .touchUpInside)
        stack.addArrangedSubview(advancedToggle)

        advancedStack.axis = .vertical
        advancedStack.spacing = 12
        advancedStack.isHidden = true
        setupAdvancedSection()
        stack.addArrangedSubview(advancedStack)
    }

    private func setupAdvancedSection() {
        let ingestTitle = LegacyUI.sectionTitle("Mac 直播 ingest")
        let ingestHint = UILabel()
        ingestHint.font = LegacyTheme.fontHint
        ingestHint.textColor = LegacyTheme.textSecondary
        ingestHint.numberOfLines = 0
        ingestHint.text = "推流到 Mac Edge 的 video-live 端口（默认 :8790），不要填 Brain :9527。"

        macIngestField.borderStyle = .roundedRect
        macIngestField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        macIngestField.autocapitalizationType = .none
        macIngestField.autocorrectionType = .no
        macIngestField.keyboardType = .URL
        macIngestField.placeholder = ParticipantStore.defaultMacIngestURL
        macIngestField.addTarget(self, action: #selector(macIngestChanged), for: .editingChanged)

        advancedStack.addArrangedSubview(ingestTitle)
        advancedStack.addArrangedSubview(ingestHint)
        advancedStack.addArrangedSubview(macIngestField)

        let micTitle = LegacyUI.sectionTitle("Home Mic 拾音")
        let micHint = UILabel()
        micHint.font = LegacyTheme.fontHint
        micHint.textColor = LegacyTheme.textSecondary
        micHint.numberOfLines = 0
        micHint.text = "Mac voice.stream HAP1（默认 :8792）。与上方直播 ingest :8790 不是同一个端口。"

        homeMicHostField.borderStyle = .roundedRect
        homeMicHostField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        homeMicHostField.autocapitalizationType = .none
        homeMicHostField.autocorrectionType = .no
        homeMicHostField.placeholder = HomeMicSettings.defaultHost
        homeMicHostField.addTarget(self, action: #selector(homeMicHostChanged), for: .editingChanged)

        homeMicPortField.borderStyle = .roundedRect
        homeMicPortField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        homeMicPortField.keyboardType = .numberPad
        homeMicPortField.placeholder = "\(HomeMicSettings.defaultPort)"
        homeMicPortField.addTarget(self, action: #selector(homeMicPortChanged), for: .editingChanged)

        let energyRow = UIStackView()
        energyRow.axis = .horizontal
        energyRow.spacing = 12
        energyRow.alignment = .center
        let energyLabel = UILabel()
        energyLabel.text = "静音不上传（省电）"
        energyLabel.font = LegacyTheme.fontHint
        energyLabel.textColor = LegacyTheme.textPrimary
        homeMicEnergySwitch.addTarget(self, action: #selector(homeMicEnergyChanged), for: .valueChanged)
        energyRow.addArrangedSubview(energyLabel)
        energyRow.addArrangedSubview(homeMicEnergySwitch)

        advancedStack.addArrangedSubview(micTitle)
        advancedStack.addArrangedSubview(micHint)
        advancedStack.addArrangedSubview(homeMicHostField)
        advancedStack.addArrangedSubview(homeMicPortField)
        advancedStack.addArrangedSubview(energyRow)

        let heartbeatTitle = LegacyUI.sectionTitle("心跳记录")
        advancedStack.addArrangedSubview(heartbeatTitle)
        advancedStack.addArrangedSubview(participantLabel)
        advancedStack.addArrangedSubview(heartbeatHistoryLabel)
    }

    @objc private func toggleAdvanced() {
        advancedVisible.toggle()
        advancedStack.isHidden = !advancedVisible
        advancedToggle.setTitle(advancedVisible ? "更多 ▲" : "更多 ▼", for: .normal)
    }

    private func refreshValues() {
        suppressSegmentCallback = true
        networkSegment.selectedIndex = ParticipantStore.preferredEndpoint.rawValue
        suppressSegmentCallback = false

        let pid = ParticipantStore.participantId
        participantLabel.text = pid.isEmpty ? "participant: 未登记" : "participant: \(pid)"
        macIngestField.text = ParticipantStore.macIngestURL
        homeMicHostField.text = HomeMicSettings.host
        homeMicPortField.text = "\(HomeMicSettings.port)"
        homeMicEnergySwitch.isOn = HomeMicSettings.energyGateEnabled
        refreshStatusLabel()
        refreshHeartbeatHistory()
    }

    private func refreshStatusLabel() {
        let preferred = ParticipantStore.preferredEndpoint.statusHint
        let active = ConnectionManager.shared.activeEndpoint.statusHint
        let viaFallback = ParticipantStore.lastHeartbeatOk
            && ConnectionManager.shared.activeEndpoint != ParticipantStore.preferredEndpoint
        if ConnectionManager.shared.isConnecting {
            statusLabel.text = "正在连接 \(preferred)…"
            statusLabel.textColor = LegacyTheme.accent
        } else if ParticipantStore.lastHeartbeatOk {
            if viaFallback {
                statusLabel.text = "连接正常 ✓\n（\(active)，家里暂不可用）"
            } else {
                statusLabel.text = "连接正常 ✓\n（\(active)）"
            }
            statusLabel.textColor = LegacyTheme.success
        } else {
            let err = ConnectionManager.shared.lastError.trimmingCharacters(in: .whitespacesAndNewlines)
            if err.isEmpty {
                statusLabel.text = "还没连上\n试试切换「家里 / 外面」"
            } else {
                statusLabel.text = "还没连上（\(preferred)）\n\(err)"
            }
            statusLabel.textColor = LegacyTheme.danger
        }
    }

    private func refreshHeartbeatHistory() {
        let records = HeartbeatLog.recent(8)
        if records.isEmpty {
            heartbeatHistoryLabel.text = "（尚无记录）"
            return
        }
        let countdown = ConnectionManager.shared.countdownText()
        let lines = HeartbeatLog.formattedLines(for: records).joined(separator: "\n")
        heartbeatHistoryLabel.text = countdown + "\n" + lines
    }

    func refreshConnectionUI() {
        refreshValues()
    }

    @objc private func macIngestChanged() {
        ParticipantStore.macIngestURL = macIngestField.text ?? ""
    }

    @objc private func homeMicHostChanged() {
        HomeMicSettings.host = homeMicHostField.text ?? ""
    }

    @objc private func homeMicPortChanged() {
        let raw = Int(homeMicPortField.text ?? "") ?? Int(HomeMicSettings.defaultPort)
        HomeMicSettings.port = UInt16(max(1, min(raw, 65_535)))
    }

    @objc private func homeMicEnergyChanged() {
        HomeMicSettings.energyGateEnabled = homeMicEnergySwitch.isOn
    }

    @objc private func reconnect() {
        ParticipantStore.participantId = ""
        ParticipantStore.lastHeartbeatOk = false
        HeartbeatLog.clear()
        ConnectionManager.shared.startAutoConnect()
        refreshValues()
        showAlert(message: "正在重新连接…")
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        refreshConnectionUI()
        countdownTimer?.invalidate()
        countdownTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.refreshHeartbeatHistory()
            self?.refreshStatusLabel()
        }
        if let timer = countdownTimer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        countdownTimer?.invalidate()
        countdownTimer = nil
    }

    private func showAlert(message: String) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }
}
