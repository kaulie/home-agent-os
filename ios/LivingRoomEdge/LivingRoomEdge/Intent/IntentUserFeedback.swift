import Foundation
import SwiftUI

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

enum IntentFeedbackStore {
    private static let key = "livingroom.intentUserFeedback.v1"

    static func load(intentId: String) -> IntentUserFeedback {
        guard let map = UserDefaults.standard.dictionary(forKey: key) as? [String: Data],
              let data = map[intentId],
              let row = try? JSONDecoder().decode(IntentUserFeedback.self, from: data) else {
            return IntentUserFeedback()
        }
        return row
    }

    static func save(intentId: String, feedback: IntentUserFeedback) {
        var map = (UserDefaults.standard.dictionary(forKey: key) as? [String: Data]) ?? [:]
        if let data = try? JSONEncoder().encode(feedback) {
            map[intentId] = data
            UserDefaults.standard.set(map, forKey: key)
        }
    }
}

struct IntentFeedbackStrip: View {
    let intentId: String
    @EnvironmentObject private var model: AppModel
    @State private var feedback = IntentUserFeedback()
    @State private var hint = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("意图理解")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .frame(width: 52, alignment: .leading)
                chipGroup(
                    choices: IntentUnderstandingFeedback.allCases,
                    selection: feedback.understanding,
                    label: { $0.label }
                ) { feedback.understanding = $0; persist() }
            }
            HStack(spacing: 6) {
                Text("响应速度")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .frame(width: 52, alignment: .leading)
                chipGroup(
                    choices: IntentSpeedFeedback.allCases,
                    selection: feedback.responseSpeed,
                    label: { $0.label }
                ) { feedback.responseSpeed = $0; persist() }
            }
            if !hint.isEmpty {
                Text(hint)
                    .font(.caption2)
                    .foregroundStyle(hint.contains("失败") || hint.contains("未同步") ? .orange : .secondary)
            }
        }
        .padding(.top, 4)
        .task(id: intentId) {
            await load()
        }
    }

    private func chipGroup<T: Hashable>(
        choices: [T],
        selection: T?,
        label: @escaping (T) -> String,
        onSelect: @escaping (T) -> Void
    ) -> some View {
        HStack(spacing: 4) {
            ForEach(choices, id: \.self) { choice in
                let selected = selection == choice
                Button {
                    onSelect(choice)
                } label: {
                    Text(label(choice))
                        .font(.caption2)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(selected ? Color.accentColor.opacity(0.15) : Color(.tertiarySystemFill))
                        .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func load() async {
        feedback = IntentFeedbackStore.load(intentId: intentId)
        let remote = await model.intentClient.fetchIntentFeedback(
            intentId: intentId,
            participantId: model.participantId,
            intentURL: model.intentServerURL
        )
        if let remote {
            feedback = remote
            IntentFeedbackStore.save(intentId: intentId, feedback: remote)
        }
    }

    private func persist() {
        IntentFeedbackStore.save(intentId: intentId, feedback: feedback)
        guard let u = feedback.understanding, let s = feedback.responseSpeed else {
            hint = ""
            return
        }
        hint = "保存中…"
        Task {
            let ok = await model.intentClient.submitIntentFeedback(
                intentId: intentId,
                participantId: model.participantId,
                understanding: u,
                responseSpeed: s,
                intentURL: model.intentServerURL
            )
            hint = ok ? "已记录" : "暂存本机（服务端未同步）"
            if ok {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                if hint == "已记录" { hint = "" }
            }
        }
    }
}
