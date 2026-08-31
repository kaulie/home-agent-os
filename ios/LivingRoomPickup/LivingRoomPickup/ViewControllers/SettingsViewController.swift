import UIKit

final class SettingsViewController: UIViewController {
    var onSaved: (() -> Void)?

    private let scrollView = UIScrollView()
    private let stack = UIStackView()
    private let hostField = UITextField()
    private let portField = UITextField()
    private let participantField = UITextField()
    private let energySwitch = UISwitch()
    private let deviceLabel = UILabel()

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "设置"
        view.backgroundColor = UIColor(red: 0.06, green: 0.07, blue: 0.10, alpha: 1)
        navigationItem.rightBarButtonItem = UIBarButtonItem(
            title: "完成",
            style: .done,
            target: self,
            action: #selector(saveAndClose)
        )
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
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: scrollView.topAnchor, constant: 20),
            stack.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -20),
            stack.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -24),
            stack.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -40),
        ])

        stack.addArrangedSubview(sectionTitle("Mac 拾音服务"))
        stack.addArrangedSubview(hintLabel("默认 mDNS 名 gateway.local。发现后下面显示实际 IP。voice.stream HAP1，默认 :8792。"))
        stack.addArrangedSubview(hintLabel("身份：\(HomeMicSettings.defaultMdnsHost)"))

        styleField(hostField, placeholder: "实际 IP（自动发现）", keyboard: .URL)
        hostField.addTarget(self, action: #selector(hostChanged), for: .editingChanged)
        stack.addArrangedSubview(hostField)

        styleField(portField, placeholder: "\(HomeMicSettings.defaultPort)", keyboard: .numberPad)
        portField.addTarget(self, action: #selector(portChanged), for: .editingChanged)
        attachDoneToolbar(to: portField)
        stack.addArrangedSubview(portField)

        let energyRow = UIStackView()
        energyRow.axis = .horizontal
        energyRow.spacing = 12
        energyRow.alignment = .center
        let energyLabel = UILabel()
        energyLabel.text = "静音不上传（省电）"
        energyLabel.font = PickupTheme.fontHint
        energyLabel.textColor = .white
        energySwitch.onTintColor = PickupTheme.success
        energySwitch.addTarget(self, action: #selector(energyChanged), for: .valueChanged)
        energyRow.addArrangedSubview(energyLabel)
        energyRow.addArrangedSubview(energySwitch)
        stack.addArrangedSubview(energyRow)

        stack.addArrangedSubview(sectionTitle("身份"))
        stack.addArrangedSubview(hintLabel("device_id 自动生成。participant_id 可选，用于与 Edge 对账。"))

        deviceLabel.font = UIFont(name: "Menlo-Regular", size: 13) ?? UIFont.systemFont(ofSize: 13)
        deviceLabel.textColor = PickupTheme.textSecondary
        deviceLabel.numberOfLines = 0
        stack.addArrangedSubview(deviceLabel)

        styleField(participantField, placeholder: "participant_id（可空）", keyboard: .default)
        participantField.autocapitalizationType = .none
        participantField.autocorrectionType = .no
        participantField.addTarget(self, action: #selector(participantChanged), for: .editingChanged)
        attachDoneToolbar(to: participantField)
        attachDoneToolbar(to: hostField)
        stack.addArrangedSubview(participantField)

        let discoverBtn = UIButton(type: .system)
        discoverBtn.setTitle("重新发现 gateway.local", for: .normal)
        discoverBtn.setTitleColor(.white, for: .normal)
        discoverBtn.titleLabel?.font = UIFont.systemFont(ofSize: 16, weight: .semibold)
        discoverBtn.addTarget(self, action: #selector(autoDiscover), for: .touchUpInside)
        discoverBtn.tag = 8801
        stack.addArrangedSubview(discoverBtn)

        stack.addArrangedSubview(sectionTitle("局域网探测日志"))
        let logSwitchRow = UIStackView()
        logSwitchRow.axis = .horizontal
        logSwitchRow.alignment = .center
        logSwitchRow.spacing = 12
        let logSwitchLabel = UILabel()
        logSwitchLabel.text = "记录探测日志"
        logSwitchLabel.font = PickupTheme.fontHint
        logSwitchLabel.textColor = .white
        let logSwitch = UISwitch()
        logSwitch.onTintColor = PickupTheme.success
        logSwitch.isOn = DiscoveryDebugLog.shared.isEnabled
        logSwitch.tag = 8803
        logSwitch.addTarget(self, action: #selector(discoveryLogEnabledChanged), for: .valueChanged)
        logSwitchRow.addArrangedSubview(logSwitchLabel)
        logSwitchRow.addArrangedSubview(logSwitch)
        stack.addArrangedSubview(logSwitchRow)
        stack.addArrangedSubview(hintLabel("默认关闭。打开后才写日志，避免本页一直刷新。"))

        let logView = UITextView()
        logView.isEditable = false
        logView.isScrollEnabled = true
        logView.font = UIFont(name: "Menlo-Regular", size: 11) ?? UIFont.systemFont(ofSize: 11)
        logView.backgroundColor = UIColor(white: 0.12, alpha: 1)
        logView.textColor = PickupTheme.textSecondary
        logView.translatesAutoresizingMaskIntoConstraints = false
        logView.heightAnchor.constraint(equalToConstant: 280).isActive = true
        logView.tag = 8802
        stack.addArrangedSubview(logView)
        applyDiscoveryLogVisibility()

        DiscoveryDebugLog.shared.onUpdate = { [weak self] in
            self?.refreshDiscoveryLog()
        }
        refreshDiscoveryLog()
    }

    private func refreshValues() {
        hostField.text = HomeMicSettings.host
        portField.text = "\(HomeMicSettings.port)"
        energySwitch.isOn = HomeMicSettings.energyGateEnabled
        participantField.text = PickupIdentity.participantId
        deviceLabel.text = "device_id: \(PickupIdentity.deviceId)"
    }

    private func sectionTitle(_ text: String) -> UILabel {
        let label = UILabel()
        label.text = text
        label.font = UIFont.systemFont(ofSize: 20, weight: .bold)
        label.textColor = .white
        return label
    }

    private func hintLabel(_ text: String) -> UILabel {
        let label = UILabel()
        label.text = text
        label.font = PickupTheme.fontHint
        label.textColor = PickupTheme.textSecondary
        label.numberOfLines = 0
        return label
    }

    private func styleField(_ field: UITextField, placeholder: String, keyboard: UIKeyboardType) {
        field.borderStyle = .roundedRect
        field.font = UIFont(name: "Menlo-Regular", size: 15) ?? UIFont.systemFont(ofSize: 15)
        field.autocapitalizationType = .none
        field.autocorrectionType = .no
        field.keyboardType = keyboard
        field.placeholder = placeholder
        field.backgroundColor = UIColor(white: 1, alpha: 0.92)
    }

    private func attachDoneToolbar(to field: UITextField) {
        let toolbar = UIToolbar()
        toolbar.sizeToFit()
        let flex = UIBarButtonItem(barButtonSystemItem: .flexibleSpace, target: nil, action: nil)
        let done = UIBarButtonItem(title: "完成", style: .done, target: self, action: #selector(dismissKeyboard))
        toolbar.items = [flex, done]
        field.inputAccessoryView = toolbar
    }

    @objc private func dismissKeyboard() {
        view.endEditing(true)
    }

    @objc private func hostChanged() {
        HomeMicSettings.host = hostField.text ?? ""
    }

    @objc private func portChanged() {
        let raw = Int(portField.text ?? "") ?? Int(HomeMicSettings.defaultPort)
        HomeMicSettings.port = UInt16(max(1, min(raw, 65_535)))
    }

    @objc private func energyChanged() {
        HomeMicSettings.energyGateEnabled = energySwitch.isOn
    }

    @objc private func participantChanged() {
        PickupIdentity.participantId = participantField.text ?? ""
    }

    private func discoveryLogSwitch() -> UISwitch? {
        stack.arrangedSubviews.compactMap { view -> UISwitch? in
            (view as? UIStackView)?.arrangedSubviews.compactMap { $0 as? UISwitch }.first { $0.tag == 8803 }
        }.first
    }

    private func applyDiscoveryLogVisibility() {
        let on = DiscoveryDebugLog.shared.isEnabled
        let logView = stack.arrangedSubviews.first(where: { $0.tag == 8802 })
        logView?.isHidden = !on
        discoveryLogSwitch()?.isOn = on
    }

    @objc private func discoveryLogEnabledChanged() {
        let on = discoveryLogSwitch()?.isOn ?? false
        DiscoveryDebugLog.shared.isEnabled = on
        applyDiscoveryLogVisibility()
        refreshDiscoveryLog()
    }

    private func refreshDiscoveryLog() {
        applyDiscoveryLogVisibility()
        let logView = stack.arrangedSubviews.first(where: { $0.tag == 8802 }) as? UITextView
        guard DiscoveryDebugLog.shared.isEnabled else { return }
        let text = DiscoveryDebugLog.shared.text
        logView?.text = text.isEmpty ? "（尚无日志；打开开关后再发现）" : text
    }

    @objc private func autoDiscover() {
        if let btn = stack.arrangedSubviews.first(where: { $0.tag == 8801 }) as? UIButton {
            btn.isEnabled = false
            btn.setTitle("正在发现…", for: .normal)
        }
        HomeMicSettings.host = ""
        HomeMicSettings.autoDiscoverGateway { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.refreshValues()
                self.refreshDiscoveryLog()
                if let btn = self.stack.arrangedSubviews.first(where: { $0.tag == 8801 }) as? UIButton {
                    btn.isEnabled = true
                    btn.setTitle("重新发现 gateway.local", for: .normal)
                }
            }
        }
    }

    @objc private func saveAndClose() {
        dismissKeyboard()
        hostChanged()
        portChanged()
        energyChanged()
        participantChanged()
        onSaved?()
        navigationController?.popViewController(animated: true)
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        dismissKeyboard()
    }
}
