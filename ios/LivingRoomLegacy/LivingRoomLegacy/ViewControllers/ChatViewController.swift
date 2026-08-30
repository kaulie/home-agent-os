import UIKit

private enum ChatInputMode {
    case typing
    case voice
}

private enum ChatRow {
    case user(String, intentId: String)
    case timeline(IntentTimeline)
    case feedback(turnId: String)
    case assistant(String, isWaiting: Bool)
}

final class ChatViewController: UIViewController, UIGestureRecognizerDelegate {
    private var turns: [ChatTurn] = []
    private let poller = IntentPoller()
    private var feedbackBusyTurnIds = Set<String>()
    private var feedbackSubmittedTurnIds = Set<String>()
    private var feedbackSubmittedMessages: [String: String] = [:]
    private var feedbackErrors: [String: String] = [:]

    private var inputMode: ChatInputMode = .typing
    private let speech = ReadingSpeechService()
    private var voicePartialText = ""
    private var voiceHoldActive = false
    private var voiceFinalizePending = false
    private var voiceFinalizeWorkItem: DispatchWorkItem?

    private let statusRow = UIView()
    private let statusDot = UIView()
    private let statusLabel = UILabel()
    private let tableView = UITableView(frame: .zero, style: .plain)
    private let inputBar = UIView()
    private let modeToggleButton = UIButton(type: .system)
    private let typingContainer = UIView()
    private let voiceContainer = UIView()
    private let inputField = UITextField()
    private let sendButton = UIButton(type: .system)
    private let voiceHintLabel = UILabel()
    private let holdMicButton = UIButton(type: .custom)
    private var inputBottomConstraint: NSLayoutConstraint?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = LegacyTheme.background
        poller.delegate = self

        setupStatusRow()
        setupTable()
        setupInputBar()
        setupKeyboardDismiss()
        speech.delegate = self
        refreshConnectionStatus()

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(keyboardWillChange(_:)),
            name: UIResponder.keyboardWillChangeFrameNotification,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(keyboardWillHide(_:)),
            name: UIResponder.keyboardWillHideNotification,
            object: nil
        )
    }

    @objc func dismissKeyboard() {
        if inputField.isFirstResponder {
            inputField.resignFirstResponder()
        }
        view.endEditing(true)
        cancelVoiceInputIfNeeded()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        dismissKeyboard()
    }

    deinit {
        speech.stop()
        NotificationCenter.default.removeObserver(self)
    }

    func refreshConnectionStatus() {
        if ConnectionManager.shared.isConnecting {
            statusDot.backgroundColor = LegacyTheme.accent
            statusLabel.text = "稍等一下…"
            statusLabel.textColor = LegacyTheme.textSecondary
        } else if ParticipantStore.lastHeartbeatOk {
            statusDot.backgroundColor = LegacyTheme.success
            statusLabel.text = "可以说话了"
            statusLabel.textColor = LegacyTheme.success
        } else {
            statusDot.backgroundColor = LegacyTheme.danger
            statusLabel.text = "连不上，请找家长"
            statusLabel.textColor = LegacyTheme.danger
        }
    }

    private func setupStatusRow() {
        statusRow.translatesAutoresizingMaskIntoConstraints = false

        statusDot.layer.cornerRadius = 6
        statusDot.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = LegacyTheme.fontHint
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        statusRow.addSubview(statusDot)
        statusRow.addSubview(statusLabel)
        view.addSubview(statusRow)

        NSLayoutConstraint.activate([
            statusRow.topAnchor.constraint(equalTo: view.topAnchor, constant: 4),
            statusRow.centerXAnchor.constraint(equalTo: view.centerXAnchor),

            statusDot.leadingAnchor.constraint(equalTo: statusRow.leadingAnchor),
            statusDot.centerYAnchor.constraint(equalTo: statusRow.centerYAnchor),
            statusDot.widthAnchor.constraint(equalToConstant: 12),
            statusDot.heightAnchor.constraint(equalToConstant: 12),

            statusLabel.leadingAnchor.constraint(equalTo: statusDot.trailingAnchor, constant: 8),
            statusLabel.topAnchor.constraint(equalTo: statusRow.topAnchor),
            statusLabel.bottomAnchor.constraint(equalTo: statusRow.bottomAnchor),
            statusLabel.trailingAnchor.constraint(equalTo: statusRow.trailingAnchor),
        ])
    }

    private func setupTable() {
        tableView.translatesAutoresizingMaskIntoConstraints = false
        tableView.separatorStyle = .none
        tableView.backgroundColor = .clear
        tableView.estimatedRowHeight = 88
        tableView.rowHeight = UITableView.automaticDimension
        tableView.dataSource = self
        tableView.delegate = self
        tableView.keyboardDismissMode = .interactive
        tableView.register(ChatMessageCell.self, forCellReuseIdentifier: ChatMessageCell.reuseId)
        tableView.register(JourneyTimelineCell.self, forCellReuseIdentifier: JourneyTimelineCell.reuseId)
        tableView.register(FeedbackStripCell.self, forCellReuseIdentifier: FeedbackStripCell.reuseId)
        view.addSubview(tableView)
        NSLayoutConstraint.activate([
            tableView.topAnchor.constraint(equalTo: statusRow.bottomAnchor, constant: 8),
            tableView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            tableView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
    }

    private func setupInputBar() {
        inputBar.backgroundColor = LegacyTheme.card
        inputBar.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(inputBar)

        modeToggleButton.setTitle("语音", for: .normal)
        modeToggleButton.setTitleColor(LegacyTheme.accent, for: .normal)
        modeToggleButton.titleLabel?.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
        modeToggleButton.backgroundColor = LegacyTheme.accentSoft
        modeToggleButton.layer.cornerRadius = 10
        modeToggleButton.layer.borderWidth = 1
        modeToggleButton.layer.borderColor = LegacyTheme.border.cgColor
        modeToggleButton.contentEdgeInsets = UIEdgeInsets(top: 6, left: 10, bottom: 6, right: 10)
        modeToggleButton.addTarget(self, action: #selector(toggleInputMode), for: .touchUpInside)
        modeToggleButton.translatesAutoresizingMaskIntoConstraints = false
        modeToggleButton.setContentHuggingPriority(.required, for: .horizontal)
        modeToggleButton.setContentCompressionResistancePriority(.required, for: .horizontal)

        typingContainer.translatesAutoresizingMaskIntoConstraints = false
        voiceContainer.translatesAutoresizingMaskIntoConstraints = false
        voiceContainer.isHidden = true

        LegacyUI.styleKidTextField(inputField, placeholder: "在这里打字…")
        inputField.returnKeyType = .send
        inputField.delegate = self
        inputField.translatesAutoresizingMaskIntoConstraints = false
        inputField.font = UIFont.systemFont(ofSize: 17)

        sendButton.setTitle("发送", for: .normal)
        sendButton.setTitleColor(LegacyTheme.accent, for: .normal)
        sendButton.titleLabel?.font = UIFont.systemFont(ofSize: 16, weight: .semibold)
        sendButton.backgroundColor = .clear
        sendButton.contentEdgeInsets = UIEdgeInsets(top: 0, left: 4, bottom: 0, right: 4)
        sendButton.addTarget(self, action: #selector(sendTapped), for: .touchUpInside)
        sendButton.translatesAutoresizingMaskIntoConstraints = false
        sendButton.setContentHuggingPriority(.required, for: .horizontal)
        sendButton.setContentCompressionResistancePriority(.required, for: .horizontal)

        voiceHintLabel.font = UIFont.systemFont(ofSize: 14, weight: .medium)
        voiceHintLabel.textColor = LegacyTheme.textSecondary
        voiceHintLabel.textAlignment = .center
        voiceHintLabel.numberOfLines = 1
        voiceHintLabel.text = "按住话筒说话"
        voiceHintLabel.translatesAutoresizingMaskIntoConstraints = false

        holdMicButton.translatesAutoresizingMaskIntoConstraints = false
        holdMicButton.adjustsImageWhenHighlighted = false
        holdMicButton.imageView?.contentMode = .scaleAspectFit
        holdMicButton.contentEdgeInsets = UIEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)
        holdMicButton.layer.cornerRadius = 44
        holdMicButton.layer.masksToBounds = false
        updateHoldMicAppearance(listening: false)
        holdMicButton.addTarget(self, action: #selector(voiceTouchDown), for: .touchDown)
        holdMicButton.addTarget(self, action: #selector(voiceTouchUp), for: [.touchUpInside, .touchUpOutside, .touchCancel])

        typingContainer.addSubview(modeToggleButton)
        typingContainer.addSubview(inputField)
        typingContainer.addSubview(sendButton)
        voiceContainer.addSubview(voiceHintLabel)
        voiceContainer.addSubview(holdMicButton)
        inputBar.addSubview(typingContainer)
        inputBar.addSubview(voiceContainer)

        inputBottomConstraint = inputBar.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor)

        NSLayoutConstraint.activate([
            inputBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            inputBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            inputBottomConstraint!,
            tableView.bottomAnchor.constraint(equalTo: inputBar.topAnchor),

            typingContainer.topAnchor.constraint(equalTo: inputBar.topAnchor, constant: 6),
            typingContainer.leadingAnchor.constraint(equalTo: inputBar.leadingAnchor),
            typingContainer.trailingAnchor.constraint(equalTo: inputBar.trailingAnchor),
            typingContainer.bottomAnchor.constraint(equalTo: inputBar.bottomAnchor, constant: -6),

            voiceContainer.topAnchor.constraint(equalTo: inputBar.topAnchor, constant: 6),
            voiceContainer.leadingAnchor.constraint(equalTo: inputBar.leadingAnchor),
            voiceContainer.trailingAnchor.constraint(equalTo: inputBar.trailingAnchor),
            voiceContainer.bottomAnchor.constraint(equalTo: inputBar.bottomAnchor, constant: -6),

            inputField.topAnchor.constraint(equalTo: typingContainer.topAnchor),
            inputField.leadingAnchor.constraint(equalTo: typingContainer.leadingAnchor, constant: 72),
            inputField.trailingAnchor.constraint(equalTo: sendButton.leadingAnchor, constant: -4),
            inputField.heightAnchor.constraint(equalToConstant: 36),
            inputField.bottomAnchor.constraint(equalTo: typingContainer.bottomAnchor),

            sendButton.trailingAnchor.constraint(equalTo: typingContainer.trailingAnchor, constant: -10),
            sendButton.centerYAnchor.constraint(equalTo: inputField.centerYAnchor),
            sendButton.heightAnchor.constraint(equalTo: inputField.heightAnchor),

            voiceHintLabel.centerYAnchor.constraint(equalTo: voiceContainer.topAnchor, constant: 14),
            voiceHintLabel.leadingAnchor.constraint(equalTo: voiceContainer.leadingAnchor, constant: 12),

            holdMicButton.topAnchor.constraint(equalTo: voiceHintLabel.bottomAnchor, constant: 6),
            holdMicButton.centerXAnchor.constraint(equalTo: voiceContainer.centerXAnchor),
            holdMicButton.widthAnchor.constraint(equalToConstant: 88),
            holdMicButton.heightAnchor.constraint(equalToConstant: 88),
            holdMicButton.bottomAnchor.constraint(equalTo: voiceContainer.bottomAnchor),
        ])
        moveModeToggle(to: typingContainer)
    }

    private var modeToggleLeadingTyping: NSLayoutConstraint?
    private var modeToggleCenterTyping: NSLayoutConstraint?
    private var modeToggleTopVoice: NSLayoutConstraint?
    private var modeToggleTrailingVoice: NSLayoutConstraint?

    private func moveModeToggle(to container: UIView) {
        modeToggleButton.removeFromSuperview()
        container.addSubview(modeToggleButton)
        modeToggleButton.translatesAutoresizingMaskIntoConstraints = false
        modeToggleLeadingTyping?.isActive = false
        modeToggleCenterTyping?.isActive = false
        modeToggleTopVoice?.isActive = false
        modeToggleTrailingVoice?.isActive = false
        if container === typingContainer {
            modeToggleLeadingTyping = modeToggleButton.leadingAnchor.constraint(equalTo: typingContainer.leadingAnchor, constant: 12)
            modeToggleCenterTyping = modeToggleButton.centerYAnchor.constraint(equalTo: inputField.centerYAnchor)
            modeToggleLeadingTyping?.isActive = true
            modeToggleCenterTyping?.isActive = true
        } else {
            modeToggleTopVoice = modeToggleButton.centerYAnchor.constraint(equalTo: voiceContainer.topAnchor, constant: 14)
            modeToggleTrailingVoice = modeToggleButton.trailingAnchor.constraint(equalTo: voiceContainer.trailingAnchor, constant: -12)
            modeToggleTopVoice?.isActive = true
            modeToggleTrailingVoice?.isActive = true
        }
    }

    private func updateHoldMicAppearance(listening: Bool) {
        let iconSize: CGFloat = 52
        let micImage = ChatIcons.microphone(diameter: iconSize, color: .white)
        holdMicButton.setImage(micImage, for: .normal)
        if listening {
            holdMicButton.backgroundColor = LegacyTheme.accent
            holdMicButton.tintColor = .white
            holdMicButton.layer.borderWidth = 0
            holdMicButton.layer.borderColor = nil
            holdMicButton.layer.shadowOpacity = 0.22
            holdMicButton.transform = CGAffineTransform(scaleX: 1.04, y: 1.04)
        } else {
            holdMicButton.backgroundColor = LegacyTheme.card
            holdMicButton.tintColor = LegacyTheme.accent
            holdMicButton.layer.borderWidth = 1
            holdMicButton.layer.borderColor = LegacyTheme.border.cgColor
            holdMicButton.layer.shadowOpacity = 0.10
            holdMicButton.transform = .identity
        }
        holdMicButton.layer.shadowColor = LegacyTheme.accent.cgColor
        holdMicButton.layer.shadowOffset = CGSize(width: 0, height: 2)
        holdMicButton.layer.shadowRadius = 5
    }

    private func applyInputMode(_ mode: ChatInputMode, animated: Bool) {
        inputMode = mode
        let showVoice = mode == .voice
        if showVoice {
            dismissKeyboard()
        } else {
            cancelVoiceInputIfNeeded()
        }
        modeToggleButton.setTitle(showVoice ? "打字" : "语音", for: .normal)
        let changes = {
            self.typingContainer.isHidden = showVoice
            self.voiceContainer.isHidden = !showVoice
            self.moveModeToggle(to: showVoice ? self.voiceContainer : self.typingContainer)
            self.view.layoutIfNeeded()
        }
        if animated {
            UIView.transition(with: inputBar, duration: 0.2, options: .transitionCrossDissolve, animations: changes)
        } else {
            changes()
        }
    }

    @objc private func toggleInputMode() {
        dismissKeyboard()
        applyInputMode(inputMode == .typing ? .voice : .typing, animated: true)
    }

    @objc private func voiceTouchDown() {
        guard inputMode == .voice else { return }
        guard !voiceHoldActive else { return }
        guard ParticipantStore.lastHeartbeatOk else {
            voiceHintLabel.text = "还连不上，请找家长"
            return
        }
        guard !ParticipantStore.participantId.isEmpty else {
            voiceHintLabel.text = "还没准备好，请找家长"
            return
        }
        voiceFinalizeWorkItem?.cancel()
        voiceFinalizePending = false
        voicePartialText = ""
        voiceHoldActive = true
        voiceHintLabel.text = "正在听…"
        updateHoldMicAppearance(listening: true)
        speech.start()
    }

    @objc private func voiceTouchUp() {
        guard voiceHoldActive else { return }
        voiceHoldActive = false
        updateHoldMicAppearance(listening: false)
        voiceHintLabel.text = voicePartialText.isEmpty ? "转文字中…" : "「\(voicePartialText)」"
        voiceFinalizePending = true
        speech.stop()
        scheduleVoiceFinalizeFallback()
    }

    private func scheduleVoiceFinalizeFallback() {
        voiceFinalizeWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.completeVoiceInput(with: self?.voicePartialText ?? "")
        }
        voiceFinalizeWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45, execute: work)
    }

    private func completeVoiceInput(with text: String) {
        guard voiceFinalizePending || voiceHoldActive else { return }
        voiceFinalizeWorkItem?.cancel()
        voiceFinalizePending = false
        voiceHoldActive = false
        updateHoldMicAppearance(listening: false)
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        voicePartialText = ""
        guard !trimmed.isEmpty else {
            voiceHintLabel.text = "没听到，再按住说一次"
            return
        }
        voiceHintLabel.text = "按住下方话筒说话"
        sendText(trimmed)
    }

    private func cancelVoiceInputIfNeeded() {
        voiceFinalizeWorkItem?.cancel()
        voiceFinalizePending = false
        if voiceHoldActive || speech.isListening {
            voiceHoldActive = false
            speech.stop()
            updateHoldMicAppearance(listening: false)
            if inputMode == .voice {
                voiceHintLabel.text = "按住话筒说话"
            }
        }
    }

    private func setupKeyboardDismiss() {
        let dismissTargets: [UIView] = [view, tableView, statusRow, inputBar, typingContainer, voiceContainer]
        for target in dismissTargets {
            let tap = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
            tap.cancelsTouchesInView = false
            tap.delegate = self
            target.addGestureRecognizer(tap)
        }
        statusRow.isUserInteractionEnabled = true
        tableView.keyboardDismissMode = .interactive
    }

    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer,
        shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
    ) -> Bool {
        true
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        guard inputField.isFirstResponder else { return false }
        if touch.view === inputField || touch.view?.isDescendant(of: inputField) == true {
            return false
        }
        if touch.view === sendButton || touch.view?.isDescendant(of: sendButton) == true {
            return false
        }
        return true
    }

    @objc private func sendTapped() {
        dismissKeyboard()
        sendCurrentText()
    }

    private func sendCurrentText() {
        let text = (inputField.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputField.text = ""
        inputField.resignFirstResponder()
        sendText(text)
    }

    private func sendText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        guard ParticipantStore.lastHeartbeatOk else {
            showAlert(message: "还连不上，请找家长帮忙。")
            return
        }

        let pid = ParticipantStore.participantId
        guard !pid.isEmpty else {
            showAlert(message: "还没准备好，请找家长帮忙。")
            return
        }

        let turn = ChatTurn(userText: trimmed, isWaiting: true, timeline: IntentTimeline.posting())
        turns.append(turn)
        reloadAndScroll()

        let url = ParticipantStore.brainIntentURL
        BrainAPI.postIntent(intentURL: url, text: trimmed, participantId: pid) { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure:
                self.updateTurn(id: turn.id) { t in
                    t.isWaiting = false
                    t.status = "failed"
                    t.assistantText = "没发出去，请再找家长。"
                    t.timeline = IntentTimeline.sendFailed("")
                }
            case .success(let snap):
                self.updateTurn(id: turn.id) { t in
                    t.intentId = snap.intentId
                    t.status = snap.status
                    t.timeline = IntentTimeline.fromSnapshot(snap)
                    if !snap.displayText.isEmpty {
                        t.assistantText = snap.displayText
                        t.isWaiting = false
                    } else {
                        t.assistantText = "想一想…"
                    }
                }
                if !snap.intentId.isEmpty {
                    self.poller.start(intentURL: url, intentId: snap.intentId)
                }
            }
        }
    }

    private func updateTurn(id: String, mutate: (inout ChatTurn) -> Void) {
        guard let idx = turns.firstIndex(where: { $0.id == id }) else { return }
        mutate(&turns[idx])
        reloadAndScroll()
    }

    private func applySnapshot(_ snap: IntentDetailSnapshot, to turnId: String) {
        guard let idx = turns.firstIndex(where: { $0.id == turnId || $0.intentId == snap.intentId }) else { return }
        turns[idx].status = snap.status
        turns[idx].timeline = IntentTimeline.fromSnapshot(snap)
        if !snap.displayText.isEmpty {
            turns[idx].assistantText = snap.displayText
        } else if turns[idx].isTerminal {
            turns[idx].assistantText = "好了"
        } else if turns[idx].assistantText.isEmpty {
            turns[idx].assistantText = "想一想…"
        }
        turns[idx].isWaiting = !turns[idx].isTerminal
    }

    private func reloadAndScroll() {
        tableView.reloadData()
        let rows = flattenedRows()
        guard !rows.isEmpty else { return }
        let last = IndexPath(row: rows.count - 1, section: 0)
        tableView.scrollToRow(at: last, at: .bottom, animated: true)
    }

    private func flattenedRows() -> [ChatRow] {
        var rows: [ChatRow] = []
        for turn in turns {
            rows.append(.user(turn.userText, intentId: turn.intentId))
            rows.append(.timeline(turn.timeline))
            if showsFeedback(for: turn) {
                rows.append(.feedback(turnId: turn.id))
            }
            if !turn.assistantText.isEmpty || turn.isWaiting {
                let text = turn.isWaiting && turn.assistantText.isEmpty ? "想一想…" : turn.assistantText
                rows.append(.assistant(text, isWaiting: turn.isWaiting))
            }
        }
        return rows
    }

    private func row(at index: Int) -> ChatRow {
        flattenedRows()[index]
    }

    private func showsFeedback(for turn: ChatTurn) -> Bool {
        Int(turn.intentId.trimmingCharacters(in: .whitespacesAndNewlines)) != nil
    }

    private func feedbackState(for turnId: String) -> FeedbackStripState {
        if feedbackBusyTurnIds.contains(turnId) {
            return .busy
        }
        if let turn = turns.first(where: { $0.id == turnId }),
           feedbackSubmittedTurnIds.contains(turnId) || DebugReportStore.isSubmitted(intentId: turn.intentId) {
            let message = feedbackSubmittedMessages[turnId] ?? "已提交反馈，正在分析。"
            return .submitted(message)
        }
        if let err = feedbackErrors[turnId], !err.isEmpty {
            return .error(err)
        }
        return .ready
    }

    private func submitFeedback(turnId: String) {
        guard let idx = turns.firstIndex(where: { $0.id == turnId }) else { return }
        let turn = turns[idx]
        guard showsFeedback(for: turn) else { return }
        if feedbackBusyTurnIds.contains(turnId) { return }
        if feedbackSubmittedTurnIds.contains(turnId) || DebugReportStore.isSubmitted(intentId: turn.intentId) {
            return
        }

        let pid = ParticipantStore.participantId
        guard !pid.isEmpty else {
            feedbackErrors[turnId] = "还没连上，请找家长"
            reloadAndScroll()
            return
        }

        feedbackBusyTurnIds.insert(turnId)
        feedbackErrors[turnId] = nil
        reloadAndScroll()

        let snapshot = LegacyDebugSnapshot.build(turn: turn)
        BrainAPI.submitDebugReport(
            intentURL: ParticipantStore.brainIntentURL,
            intentId: turn.intentId,
            participantId: pid,
            clientSnapshot: snapshot
        ) { [weak self] result in
            guard let self = self else { return }
            self.feedbackBusyTurnIds.remove(turnId)
            switch result {
            case .failure(let err):
                self.feedbackErrors[turnId] = err.message
            case .success(let report):
                if report.ok {
                    self.feedbackSubmittedTurnIds.insert(turnId)
                    self.feedbackSubmittedMessages[turnId] = report.message.isEmpty
                        ? "已提交反馈，正在分析。"
                        : report.message
                    DebugReportStore.markSubmitted(intentId: turn.intentId)
                    self.feedbackErrors[turnId] = nil
                } else {
                    self.feedbackErrors[turnId] = report.error.isEmpty ? "提交失败" : report.error
                }
            }
            self.reloadAndScroll()
        }
    }

    private func showAlert(message: String) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }

    @objc private func keyboardWillHide(_ note: Notification) {
        inputBottomConstraint?.constant = 0
        guard let duration = note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double else {
            view.layoutIfNeeded()
            return
        }
        UIView.animate(withDuration: duration) {
            self.view.layoutIfNeeded()
        }
    }

    @objc private func keyboardWillChange(_ note: Notification) {
        guard
            let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect,
            let duration = note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double
        else { return }
        let converted = view.convert(frame, from: nil)
        let overlap = max(0, view.bounds.maxY - converted.origin.y - view.safeAreaInsets.bottom)
        inputBottomConstraint?.constant = -overlap
        UIView.animate(withDuration: duration) {
            self.view.layoutIfNeeded()
        }
    }
}

extension ChatViewController: UITableViewDataSource, UITableViewDelegate {
    func scrollViewWillBeginDragging(_ scrollView: UIScrollView) {
        dismissKeyboard()
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: false)
        dismissKeyboard()
    }

    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        flattenedRows().count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        switch row(at: indexPath.row) {
        case .user(let text, let intentId):
            let cell = tableView.dequeueReusableCell(withIdentifier: ChatMessageCell.reuseId, for: indexPath) as! ChatMessageCell
            cell.configure(text: text, isUser: true, isWaiting: false, intentId: intentId)
            return cell
        case .timeline(let timeline):
            let cell = tableView.dequeueReusableCell(withIdentifier: JourneyTimelineCell.reuseId, for: indexPath) as! JourneyTimelineCell
            cell.configure(timeline: timeline)
            return cell
        case .feedback(let turnId):
            let cell = tableView.dequeueReusableCell(withIdentifier: FeedbackStripCell.reuseId, for: indexPath) as! FeedbackStripCell
            cell.configure(state: feedbackState(for: turnId))
            cell.onTap = { [weak self] in
                self?.submitFeedback(turnId: turnId)
            }
            return cell
        case .assistant(let text, let isWaiting):
            let cell = tableView.dequeueReusableCell(withIdentifier: ChatMessageCell.reuseId, for: indexPath) as! ChatMessageCell
            cell.configure(text: text, isUser: false, isWaiting: isWaiting)
            return cell
        }
    }
}

extension ChatViewController: UITextFieldDelegate {
    func textFieldShouldReturn(_ textField: UITextField) -> Bool {
        let text = (textField.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            dismissKeyboard()
            return true
        }
        sendCurrentText()
        return true
    }
}

extension ChatViewController: IntentPollerDelegate {
    func poller(_ poller: IntentPoller, didUpdate snapshot: IntentDetailSnapshot) {
        guard let idx = turns.firstIndex(where: { $0.intentId == snapshot.intentId }) else { return }
        applySnapshot(snapshot, to: turns[idx].id)
        reloadAndScroll()
    }

    func poller(_ poller: IntentPoller, didFail intentId: String, error: String) {
        guard let idx = turns.firstIndex(where: { $0.intentId == intentId }) else { return }
        if !turns[idx].isTerminal {
            turns[idx].assistantText = "出错了，请找家长帮忙。"
        }
        reloadAndScroll()
    }
}

extension ChatViewController: ReadingSpeechServiceDelegate {
    func speechService(_ service: ReadingSpeechService, didUpdatePartial text: String) {
        guard voiceHoldActive || voiceFinalizePending else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        voicePartialText = trimmed
        if voiceHoldActive {
            voiceHintLabel.text = trimmed
        }
    }

    func speechService(_ service: ReadingSpeechService, didFinalize text: String) {
        guard voiceFinalizePending || voiceHoldActive else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            voicePartialText = trimmed
        }
        if voiceFinalizePending {
            completeVoiceInput(with: voicePartialText)
        }
    }

    func speechService(_ service: ReadingSpeechService, didUpdateStatus text: String) {
        if voiceHoldActive, !text.isEmpty {
            voiceHintLabel.text = "正在听…"
        }
    }

    func speechService(_ service: ReadingSpeechService, didFail message: String) {
        voiceFinalizeWorkItem?.cancel()
        voiceFinalizePending = false
        voiceHoldActive = false
        updateHoldMicAppearance(listening: false)
        voiceHintLabel.text = message.isEmpty ? "请再试一次" : message
    }

    func speechService(_ service: ReadingSpeechService, didUpdateLevel level: Float) {
        guard voiceHoldActive else { return }
        holdMicButton.alpha = CGFloat(0.88 + min(0.12, level * 0.35))
    }
}
