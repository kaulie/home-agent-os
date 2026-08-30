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
        stack.addArrangedSubview(hintLabel("voice.stream HAP1，默认 :8792。手机与 Mac 需同一 Wi‑Fi。"))

        styleField(hostField, placeholder: HomeMicSettings.defaultHost, keyboard: .URL)
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
