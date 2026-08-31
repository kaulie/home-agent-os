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
    private let homeBrainIPLabel = UILabel()
    private let macIngestField = UITextField()
    private let macIngestMdnsLabel = UILabel()
    private let discoverButton = UIButton(type: .system)
    private let discoveryLogSwitch = UISwitch()
    private let discoveryLogTextView = UITextView()
    private let clearDiscoveryLogButton = UIButton(type: .system)
    private let copyDiscoveryLogButton = UIButton(type: .system)
    private let discoveryLogButtons = UIStackView()
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
        brainHint.text = "局域网身份是 http://brain.local:9527。自动发现后显示实际 IP；HTTP 走 IP。云端仍是固定 IP。"

        homeBrainField.borderStyle = .roundedRect
        homeBrainField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        homeBrainField.autocapitalizationType = .none
        homeBrainField.autocorrectionType = .no
        homeBrainField.keyboardType = .URL
        homeBrainField.isEnabled = false
        homeBrainField.text = ParticipantStore.defaultHomeBrainIntentURL

        homeBrainIPLabel.font = LegacyTheme.fontHint
        homeBrainIPLabel.textColor = LegacyTheme.textSecondary
        homeBrainIPLabel.numberOfLines = 0

        advancedStack.addArrangedSubview(brainTitle)
        advancedStack.addArrangedSubview(brainHint)
        advancedStack.addArrangedSubview(homeBrainField)
        advancedStack.addArrangedSubview(homeBrainIPLabel)

        let ingestTitle = LegacyUI.sectionTitle("Mac 直播 ingest")
        let ingestHint = UILabel()
        ingestHint.font = LegacyTheme.fontHint
        ingestHint.textColor = LegacyTheme.textSecondary
        ingestHint.numberOfLines = 0
        ingestHint.text = "默认 http://gateway.local:8790。发现后下面填实际 IP。"

        macIngestMdnsLabel.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        macIngestMdnsLabel.textColor = LegacyTheme.textSecondary
        macIngestMdnsLabel.text = ParticipantStore.defaultMacIngestURL

        macIngestField.borderStyle = .roundedRect
        macIngestField.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        macIngestField.autocapitalizationType = .none
        macIngestField.autocorrectionType = .no
        macIngestField.keyboardType = .URL
        macIngestField.placeholder = "实际 IP（自动发现）"
        macIngestField.addTarget(self, action: #selector(macIngestChanged), for: .editingChanged)
        attachDoneToolbar(to: macIngestField)

        advancedStack.addArrangedSubview(ingestTitle)
        advancedStack.addArrangedSubview(ingestHint)
        advancedStack.addArrangedSubview(macIngestMdnsLabel)
        advancedStack.addArrangedSubview(macIngestField)

        LegacyUI.styleSecondaryButton(discoverButton, title: "自动发现")
        discoverButton.addTarget(self, action: #selector(autoDiscover), for: .touchUpInside)
        advancedStack.addArrangedSubview(discoverButton)

        let discoverHint = UILabel()
        discoverHint.font = LegacyTheme.fontHint
        discoverHint.textColor = LegacyTheme.textSecondary
        discoverHint.numberOfLines = 0
        discoverHint.text = "点一下用 mDNS 找 brain.local / gateway.local，并把实际 IP 填到上面。"
        advancedStack.addArrangedSubview(discoverHint)

        let discoveryLogTitle = LegacyUI.sectionTitle("局域网探测日志")
        advancedStack.addArrangedSubview(discoveryLogTitle)

        let logSwitchRow = UIStackView()
        logSwitchRow.axis = .horizontal
        logSwitchRow.alignment = .center
        logSwitchRow.spacing = 12
        let logSwitchLabel = UILabel()
        logSwitchLabel.text = "记录探测日志"
        logSwitchLabel.font = LegacyTheme.fontBody
        logSwitchLabel.textColor = LegacyTheme.textPrimary
        discoveryLogSwitch.onTintColor = LegacyTheme.accent
        discoveryLogSwitch.isOn = DiscoveryDebugLog.shared.isEnabled
        discoveryLogSwitch.addTarget(self, action: #selector(discoveryLogEnabledChanged), for: .valueChanged)
        logSwitchRow.addArrangedSubview(logSwitchLabel)
        logSwitchRow.addArrangedSubview(discoveryLogSwitch)
        advancedStack.addArrangedSubview(logSwitchRow)

        let logHint = UILabel()
        logHint.font = LegacyTheme.fontHint
        logHint.textColor = LegacyTheme.textSecondary
        logHint.numberOfLines = 0
        logHint.text = "默认关闭。打开后才写入日志，避免设置页一直刷新。"
        advancedStack.addArrangedSubview(logHint)

        discoveryLogTextView.isEditable = false
        discoveryLogTextView.isScrollEnabled = true
        discoveryLogTextView.font = UIFont(name: "Menlo-Regular", size: 11) ?? UIFont.systemFont(ofSize: 11)
        discoveryLogTextView.backgroundColor = LegacyTheme.background
        discoveryLogTextView.textColor = LegacyTheme.textSecondary
        discoveryLogTextView.textContainerInset = UIEdgeInsets(top: 8, left: 4, bottom: 8, right: 4)
        discoveryLogTextView.translatesAutoresizingMaskIntoConstraints = false
        discoveryLogTextView.heightAnchor.constraint(equalToConstant: 160).isActive = true
        advancedStack.addArrangedSubview(discoveryLogTextView)

        discoveryLogButtons.axis = .horizontal
        discoveryLogButtons.spacing = 12
        LegacyUI.styleSecondaryButton(clearDiscoveryLogButton, title: "清空")
        clearDiscoveryLogButton.addTarget(self, action: #selector(clearDiscoveryLog), for: .touchUpInside)
        LegacyUI.styleSecondaryButton(copyDiscoveryLogButton, title: "复制到剪贴板")
        copyDiscoveryLogButton.addTarget(self, action: #selector(copyDiscoveryLog), for: .touchUpInside)
        discoveryLogButtons.addArrangedSubview(clearDiscoveryLogButton)
        discoveryLogButtons.addArrangedSubview(copyDiscoveryLogButton)
        advancedStack.addArrangedSubview(discoveryLogButtons)
        applyDiscoveryLogVisibility()

        DiscoveryDebugLog.shared.onUpdate = { [weak self] in
            self?.refreshDiscoveryLog()
        }
        refreshDiscoveryLog()

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
        homeBrainField.text = ParticipantStore.defaultHomeBrainIntentURL
        let resolved = ParticipantStore.homeBrainResolvedIntentURL
        if resolved.isEmpty {
            homeBrainIPLabel.text = "实际 IP：尚未发现"
        } else {
            homeBrainIPLabel.text = "实际 IP：\(BrainURL.displayBase(from: resolved))"
        }
        macIngestField.text = ParticipantStore.macIngestConnectURL.isEmpty
            ? ""
            : ParticipantStore.macIngestConnectURL
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

    /// Re-run mDNS discovery and fill the LAN slots with the discovered
    /// well-known DNS hostnames (`brain.local` / `gateway.local`) instead of IPs.
    @objc private func autoDiscover() {
        DiscoveryDebugLog.shared.log("Legacy settings: 自动发现 tapped", category: "connect")
        discoverButton.isEnabled = false
        discoverButton.setTitle("正在自动发现…", for: .normal)
        ParticipantStore.clearDiscoveredEndpoints()
        refreshValues()

        let group = DispatchGroup()
        var foundBrain = false
        var foundGateway = false

        group.enter()
        MdnsDiscovery.resolveBrainForAutoDiscover(mdnsTimeout: 6) { brain in
            if let brain {
                ParticipantStore.applyDiscoveredBrain(brain)
                foundBrain = MdnsDiscovery.isUsableLanIPv4(brain.host)
            }
            group.leave()
        }

        group.enter()
        MdnsDiscovery.resolveGatewayForAutoDiscover(mdnsTimeout: 6) { gateway in
            if let gateway {
                ParticipantStore.applyDiscoveredGateway(gateway)
                foundGateway = MdnsDiscovery.isUsableLanIPv4(gateway.host)
            }
            group.leave()
        }

        group.notify(queue: .main) { [weak self] in
            guard let self = self else { return }
            self.discoverButton.isEnabled = true
            self.discoverButton.setTitle("自动发现", for: .normal)
            self.refreshValues()
            self.presentDiscoverResult(foundBrain: foundBrain, foundGateway: foundGateway)
            if foundBrain {
                ConnectionManager.shared.connectAfterHomeDiscover()
            } else {
                DiscoveryDebugLog.shared.log("auto-discover finished: no Brain, skip register", category: "connect")
            }
        }
    }

    private func presentDiscoverResult(foundBrain: Bool, foundGateway: Bool) {
        let resolved = ParticipantStore.homeBrainResolvedIntentURL
        let brainBase = BrainURL.displayBase(from: resolved)
        let brainOK = foundBrain && MdnsDiscovery.isUsableLanIPv4(BrainURL.ipv4Host(from: resolved) ?? "")
        let gwURL = ParticipantStore.macIngestConnectURL
        let gwOK = foundGateway && MdnsDiscovery.isUsableLanIPv4(BrainURL.ipv4Host(from: gwURL) ?? "")

        if !brainOK && !gwOK {
            showAlert(message: "没找到可用的 Brain / Mac。\n\n请确认 iPhone 与 Mac 在同一 WiFi，并已重启 Brain 与 Mac Edge。")
            return
        }

        var lines = ["发现结果", ""]
        if brainOK {
            lines.append("Brain：\(brainBase)")
        } else {
            lines.append("Brain：未发现（请检查 Brain 是否在运行）")
        }
        if gwOK {
            lines.append("直播：\(gwURL)")
        } else {
            lines.append("直播：未发现（请检查 Mac Edge 是否在运行）")
        }
        showAlert(message: lines.joined(separator: "\n"))
    }

    private func applyDiscoveryLogVisibility() {
        let on = DiscoveryDebugLog.shared.isEnabled
        discoveryLogTextView.isHidden = !on
        discoveryLogButtons.isHidden = !on
    }

    @objc private func discoveryLogEnabledChanged() {
        DiscoveryDebugLog.shared.isEnabled = discoveryLogSwitch.isOn
        applyDiscoveryLogVisibility()
        refreshDiscoveryLog()
    }

    private func refreshDiscoveryLog() {
        applyDiscoveryLogVisibility()
        guard DiscoveryDebugLog.shared.isEnabled else { return }
        let text = DiscoveryDebugLog.shared.text
        discoveryLogTextView.text = text.isEmpty
            ? "（尚无日志；打开开关后点「自动发现」）"
            : text
        let end = discoveryLogTextView.text.count
        if end > 0 {
            discoveryLogTextView.scrollRangeToVisible(NSRange(location: end - 1, length: 1))
        }
    }

    @objc private func clearDiscoveryLog() {
        DiscoveryDebugLog.shared.clear()
        refreshDiscoveryLog()
    }

    @objc private func copyDiscoveryLog() {
        UIPasteboard.general.string = DiscoveryDebugLog.shared.text
        showAlert(message: "已复制探测日志")
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
