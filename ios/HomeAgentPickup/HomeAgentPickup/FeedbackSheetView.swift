import PhotosUI
import SwiftUI

struct FeedbackSheetView: View {
    @EnvironmentObject private var model: PickupViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var selected: PickupFeedbackProblemType?
    @State private var intentIdText = PickupSettings.defaultFeedbackIntentId
    @State private var detail = ""
    @State private var localError = ""
    @State private var successMessage = ""
    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var pendingAttachments: [PendingPickupFeedbackAttachment] = []

    private let maxAttachments = 3
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
                    Text("选择问题类型并填写关联 Intent 编号。可添加照片帮助我们定位问题。")
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

                Section {
                    HStack {
                        Text("照片")
                        Spacer()
                        Text("\(pendingAttachments.count)/\(maxAttachments)")
                            .foregroundStyle(.secondary)
                    }
                    if !pendingAttachments.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 10) {
                                ForEach(pendingAttachments) { pending in
                                    ZStack(alignment: .topTrailing) {
                                        Image(uiImage: pending.preview)
                                            .resizable()
                                            .scaledToFill()
                                            .frame(width: 88, height: 88)
                                            .clipShape(RoundedRectangle(cornerRadius: 10))
                                        Button {
                                            pendingAttachments.removeAll { $0.id == pending.id }
                                            pickerItems = []
                                        } label: {
                                            Image(systemName: "xmark.circle.fill")
                                                .font(.system(size: 18))
                                                .foregroundStyle(.white, Color.black.opacity(0.55))
                                        }
                                        .offset(x: 6, y: -6)
                                    }
                                }
                            }
                        }
                    }
                    if pendingAttachments.count < maxAttachments {
                        PhotosPicker(
                            selection: $pickerItems,
                            maxSelectionCount: maxAttachments - pendingAttachments.count,
                            matching: .images
                        ) {
                            Label("从相册添加照片", systemImage: "photo.on.rectangle")
                        }
                        .disabled(busy)
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
                        .disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "提交中…" : "提交") { submit() }
                        .disabled(!canSubmit || busy)
                }
            }
            .onChange(of: pickerItems) { items in
                Task { await importPickerImages(items) }
            }
        }
    }

    private func importPickerImages(_ items: [PhotosPickerItem]) async {
        guard !items.isEmpty else { return }
        var imported: [PendingPickupFeedbackAttachment] = []
        for item in items {
            guard pendingAttachments.count + imported.count < maxAttachments else { break }
            if let data = try? await item.loadTransferable(type: Data.self),
               let image = UIImage(data: data) {
                imported.append(.image(image))
            }
        }
        await MainActor.run {
            pendingAttachments.append(contentsOf: imported)
            if pendingAttachments.count > maxAttachments {
                pendingAttachments = Array(pendingAttachments.prefix(maxAttachments))
            }
            pickerItems = []
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
            userSummary: summary,
            attachments: pendingAttachments
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
