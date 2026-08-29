import SwiftUI

struct FeedbackSheetView: View {
    @EnvironmentObject private var model: PickupViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var selected: PickupFeedbackProblemType?
    @State private var intentIdText = PickupSettings.defaultFeedbackIntentId
    @State private var detail = ""
    @State private var localError = ""
    @State private var successMessage = ""

    private var busy: Bool { model.feedbackBusy }

    private var canSubmit: Bool {
        guard selected != nil, Int(intentIdText.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0 > 0 else {
            return false
        }
        if selected == .other {
            return !detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        return true
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("选择问题类型并填写关联 Intent 编号。我们会自动附带 Home Mic 现场信息。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("问题类型") {
                    ForEach(PickupFeedbackProblemType.allCases) { option in
                        Button {
                            selected = option
                            localError = ""
                        } label: {
                            HStack {
                                Text(option.label)
                                    .foregroundStyle(.primary)
                                Spacer()
                                if selected == option {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(.orange)
                                }
                            }
                        }
                    }
                }

                Section("关联 Intent") {
                    TextField("Intent 编号（必填）", text: $intentIdText)
                        .keyboardType(.numberPad)
                }

                if selected == .other {
                    Section("说明") {
                        TextField("请描述问题", text: $detail, axis: .vertical)
                            .lineLimit(3...6)
                    }
                }

                Section("现场快照（将自动提交）") {
                    LabeledContent("服务", value: model.serverLabel)
                    LabeledContent("TCP", value: model.connectionLabel)
                    LabeledContent("采集", value: model.captureLabel)
                    LabeledContent("模式", value: model.modeLabel)
                    if !model.lastError.isEmpty {
                        Text(model.lastError).font(.footnote).foregroundStyle(.red)
                    }
                }

                if !localError.isEmpty {
                    Section {
                        Text(localError).foregroundStyle(.red).font(.footnote)
                    }
                }
                if !successMessage.isEmpty {
                    Section {
                        Text(successMessage).foregroundStyle(.green).font(.footnote)
                    }
                }
            }
            .navigationTitle("提交反馈")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "提交中…" : "提交") { submit() }
                        .disabled(!canSubmit || busy)
                }
            }
        }
    }

    private func submit() {
        guard let selected else { return }
        localError = ""
        successMessage = ""
        let summary: String
        if selected == .other {
            summary = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        } else {
            let extra = detail.trimmingCharacters(in: .whitespacesAndNewlines)
            summary = extra.isEmpty ? selected.label : "\(selected.label)：\(extra)"
        }
        model.submitFeedback(
            problemType: selected,
            intentIdText: intentIdText,
            userSummary: summary
        ) { ok, message in
            if ok {
                successMessage = message
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                    dismiss()
                }
            } else {
                localError = message
            }
        }
    }
}
