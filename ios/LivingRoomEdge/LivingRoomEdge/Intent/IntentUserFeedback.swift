import Foundation
import PhotosUI
import SwiftUI
import UIKit

enum IntentUnderstandingFeedback: String, CaseIterable, Codable, Equatable {
    case accurate
    case inaccurate

    var label: String {
        switch self {
        case .accurate: return "准确"
        case .inaccurate: return "不准确"
        }
    }
}

enum IntentSpeedFeedback: String, CaseIterable, Codable, Equatable {
    case fast
    case normal
    case slow

    var label: String {
        switch self {
        case .fast: return "快"
        case .normal: return "一般"
        case .slow: return "慢"
        }
    }
}

struct IntentUserFeedback: Codable, Equatable {
    var understanding: IntentUnderstandingFeedback?
    var responseSpeed: IntentSpeedFeedback?

    enum CodingKeys: String, CodingKey {
        case understanding
        case responseSpeed = "response_speed"
    }

    var isComplete: Bool {
        understanding != nil && responseSpeed != nil
    }
}

enum DebugReportStore {
    private static let key = "livingroom.debugReportSubmitted.v1"

    static func isSubmitted(intentId: String) -> Bool {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return false }
        let set = UserDefaults.standard.array(forKey: key) as? [String] ?? []
        return set.contains(id)
    }

    static func markSubmitted(intentId: String) {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        var set = Set(UserDefaults.standard.array(forKey: key) as? [String] ?? [])
        set.insert(id)
        UserDefaults.standard.set(Array(set), forKey: key)
    }
}

enum UserFeedbackProblemType: String, CaseIterable, Identifiable, Equatable {
    case intentUnderstanding = "intent_understanding"
    case executionError = "execution_error"
    case slowResponse = "slow_response"
    case other = "other"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .intentUnderstanding: return "意图理解不准确"
        case .executionError: return "执行报错"
        case .slowResponse: return "响应速度太慢"
        case .other: return "其他"
        }
    }
}

struct UserFeedbackSheet: View {
    let turn: ChatTurn
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var selected: UserFeedbackProblemType?
    @State private var otherDetail = ""
    @State private var localError = ""
    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var pendingAttachments: [PendingFeedbackAttachment] = []
    @FocusState private var otherDetailFocused: Bool

    private let maxAttachments = 3

    private var busy: Bool {
        model.isDevBugBusy(turnId: turn.id)
    }

    private var trimmedOtherDetail: String {
        otherDetail.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var canSubmit: Bool {
        guard let selected else { return false }
        if selected == .other {
            return !trimmedOtherDetail.isEmpty
        }
        return true
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("请选择本次体验的问题类型，我们会自动收集执行现场并交给 Dev Agent 分析。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    VStack(spacing: 10) {
                        ForEach(UserFeedbackProblemType.allCases) { option in
                            let picked = selected == option
                            Button {
                                selected = option
                                localError = ""
                                if option != .other {
                                    otherDetail = ""
                                    otherDetailFocused = false
                                }
                            } label: {
                                HStack {
                                    Text(option.label)
                                        .font(.body.weight(.medium))
                                        .foregroundStyle(.primary)
                                    Spacer()
                                    Image(systemName: picked ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(picked ? Color.accentColor : Color.secondary)
                                }
                                .padding(.horizontal, 14)
                                .padding(.vertical, 12)
                                .background(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .fill(picked ? Color.accentColor.opacity(0.12) : Color(.tertiarySystemFill))
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    if selected == .other {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("补充说明")
                                .font(.subheadline.weight(.semibold))
                            TextField(
                                "请描述遇到的问题或期望…",
                                text: $otherDetail,
                                axis: .vertical
                            )
                            .lineLimit(3...6)
                            .focused($otherDetailFocused)
                            .padding(12)
                            .background(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(Color(.tertiarySystemFill))
                            )
                        }
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("附件")
                                .font(.subheadline.weight(.semibold))
                            Spacer()
                            Text("\(pendingAttachments.count)/\(maxAttachments)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Text("可附最多 \(maxAttachments) 个附件（当前支持图片，后续可扩展文件/音频）。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if !pendingAttachments.isEmpty {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 10) {
                                    ForEach(pendingAttachments) { pending in
                                        ZStack(alignment: .topTrailing) {
                                            Image(uiImage: pending.preview)
                                                .resizable()
                                                .scaledToFill()
                                                .frame(width: 88, height: 88)
                                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                            Button {
                                                pendingAttachments.removeAll { $0.id == pending.id }
                                                syncPickerItems()
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
                                Label("添加图片附件", systemImage: "paperclip")
                                    .font(.subheadline.weight(.semibold))
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 12)
                                    .background(
                                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                                            .fill(Color(.tertiarySystemFill))
                                    )
                            }
                            .disabled(busy)
                        }
                    }

                    if !localError.isEmpty {
                        Text(localError)
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
                .padding(20)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("一键反馈")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                        .disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button("提交") { submit() }
                            .disabled(!canSubmit)
                    }
                }
            }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .onChange(of: pickerItems) { _, items in
            Task { await importPickerImages(items) }
        }
        .onChange(of: selected) { _, next in
            if next == .other {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                    otherDetailFocused = true
                }
            }
        }
    }

    private func syncPickerItems() {
        pickerItems = []
    }

    private func importPickerImages(_ items: [PhotosPickerItem]) async {
        guard !items.isEmpty else { return }
        var imported: [PendingFeedbackAttachment] = []
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
            syncPickerItems()
        }
    }

    private func submit() {
        guard let selected else {
            localError = "请先选择问题类型"
            return
        }
        if selected == .other && trimmedOtherDetail.isEmpty {
            localError = "请填写补充说明"
            return
        }
        localError = ""
        model.submitUserFeedback(
            turnId: turn.id,
            problemType: selected,
            detail: selected == .other ? trimmedOtherDetail : "",
            attachments: pendingAttachments
        ) { ok, message in
            if ok {
                dismiss()
            } else {
                localError = message.isEmpty ? "提交失败" : message
            }
        }
    }
}

struct DebugBugReportStrip: View {
    let turn: ChatTurn
    @EnvironmentObject private var model: AppModel
    @State private var showFeedbackSheet = false

    private var submitted: Bool {
        model.isDevBugSubmitted(intentId: turn.intentId)
    }

    private var busy: Bool {
        model.isDevBugBusy(turnId: turn.id)
    }

    private var error: String? {
        model.devBugError(for: turn.id)
    }

    private var canSubmit: Bool {
        ChatTurn.isBrainIntentId(turn.intentId) && !submitted
    }

    var body: some View {
        Group {
            if !canSubmit && error == nil {
                if submitted {
                    Text("已提交反馈，正在分析。")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    if canSubmit {
                        HStack {
                            Spacer(minLength: 0)
                            Button {
                                showFeedbackSheet = true
                            } label: {
                                if busy {
                                    HStack(spacing: 6) {
                                        ProgressView()
                                            .controlSize(.small)
                                        Text("提交中…")
                                            .font(.caption2)
                                    }
                                } else {
                                    Text("一键反馈")
                                        .font(.caption2.weight(.semibold))
                                }
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.mini)
                            .tint(Color(red: 0.82, green: 0.70, blue: 0.48))
                            .disabled(busy)
                        }
                    }
                    if let error, !error.isEmpty {
                        Text(error)
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }
                }
                .padding(.top, 4)
                .sheet(isPresented: $showFeedbackSheet) {
                    UserFeedbackSheet(turn: turn)
                        .environmentObject(model)
                }
            }
        }
    }
}
