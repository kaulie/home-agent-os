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
    private let homeBrainField = UITextField()
    private let macIngestField = UITextField()
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
        scrollView.keyboardDismissMode = .onDrag
        view.addSubview(scrollView)
        let tap = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
        tap.cancelsTouchesInView = false
        scrollView.addGestureRecognizer(tap)
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
        let brainTitle = LegacyUI.sectionTitle("家里 Brain")
        let brainHint = UILabel()
        brainHint.font = LegacyTheme.fontHint
        brainHint.textColor = LegacyTheme.textSecondary
        brainHint.numberOfLines = 0
        brainHint.text = "局域网 Brain Intent（默认 :9527）。与下面 Mac 直播 ingest 分开填。"

        homeBrainField.borderStyle = .roundedRect
        homeBrainField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        homeBrainField.autocapitalizationType = .none
        homeBrainField.autocorrectionType = .no
        homeBrainField.keyboardType = .URL
        homeBrainField.placeholder = ParticipantStore.defaultHomeBrainIntentURL
        homeBrainField.addTarget(self, action: #selector(homeBrainChanged), for: .editingChanged)
        attachDoneToolbar(to: homeBrainField)

        advancedStack.addArrangedSubview(brainTitle)
        advancedStack.addArrangedSubview(brainHint)
        advancedStack.addArrangedSubview(homeBrainField)

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
        attachDoneToolbar(to: macIngestField)

        advancedStack.addArrangedSubview(ingestTitle)
        advancedStack.addArrangedSubview(ingestHint)
        advancedStack.addArrangedSubview(macIngestField)

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
        homeBrainField.text = ParticipantStore.homeBrainIntentURL
        macIngestField.text = ParticipantStore.macIngestURL
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

    @objc private func dismissKeyboard() {
        view.endEditing(true)
    }

    private func attachDoneToolbar(to field: UITextField) {
        let toolbar = UIToolbar()
        toolbar.sizeToFit()
        let flex = UIBarButtonItem(barButtonSystemItem: .flexibleSpace, target: nil, action: nil)
        let done = UIBarButtonItem(title: "完成", style: .done, target: self, action: #selector(dismissKeyboard))
        toolbar.items = [flex, done]
        field.inputAccessoryView = toolbar
    }

    @objc private func homeBrainChanged() {
        ParticipantStore.homeBrainIntentURL = homeBrainField.text ?? ""
    }

    @objc private func macIngestChanged() {
        ParticipantStore.macIngestURL = macIngestField.text ?? ""
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
        dismissKeyboard()
        countdownTimer?.invalidate()
        countdownTimer = nil
    }

    private func showAlert(message: String) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }
}
