import Foundation
import Combine

struct ChatTurn: Identifiable, Equatable {
    let id: UUID
    var intentId: String
    let createdAt: Date
    var userText: String
    var source: String
    var journey: IntentJourney
    var assistantText: String?
    var awaitingTerminal: Bool

    static func fromHistory(_ snapshot: IntentJobSnapshot) -> ChatTurn {
        let journey = IntentJourney.hydrated(from: snapshot)
        return ChatTurn(
            id: UUID(),
            intentId: snapshot.jobId,
            createdAt: snapshot.createdAt ?? Date(),
            userText: snapshot.text,
            source: snapshot.source,
            journey: journey,
            assistantText: ChatTurn.assistantText(for: journey),
            awaitingTerminal: !snapshot.wireStatus.isTerminal
        )
    }

    static func assistantText(for journey: IntentJourney) -> String {
        if journey.timedOut, !journey.terminal {
            let err = journey.error?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return err.isEmpty ? "等待超时，服务端尚未到达终态" : err
        }
        if journey.current == .failed {
            let err = journey.error?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return err.isEmpty ? "意图失败" : err
        }
        if let pres = journey.presentation, pres.type == .text || pres.type == .html, !pres.text.isEmpty {
            return pres.text
        }
        return ""
    }
}

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    static let defaultIntentURL = IntentClient.defaultIntentURL

    let intentClient = IntentClient()
    let intentJourney = IntentJourneyStore()

    @Published var intentServerURL = AppModel.defaultIntentURL
    @Published private(set) var turns: [ChatTurn] = []
    @Published private(set) var activeIntentJourney: IntentJourney?
    @Published private(set) var lastResponse: String = ""
    @Published private(set) var sending = false
    @Published private(set) var participantId = ParticipantStore.participantId
    @Published private(set) var clientHint = ParticipantStore.clientHint
    @Published private(set) var historyNotice = ""
    @Published private(set) var skipScrollToLatest = false

    /// In-flight user turn waiting for succeeded / failed (or send failure / timeout).
    private var pendingTurnId: UUID?
    private var historyNextBeforeId: Int?
    private var historyExhausted = false

    private var cancellables = Set<AnyCancellable>()

    private init() {
        intentJourney.$activeJourney
            .receive(on: RunLoop.main)
            .sink { [weak self] journey in
                self?.activeIntentJourney = journey
                self?.syncPendingTurn(with: journey)
            }
            .store(in: &cancellables)

        Task { await ensureRegistered(serverURL: intentServerURL, force: true) }
    }

    /// Composer stays closed until the current turn reaches a terminal reply.
    var inputLocked: Bool {
        sending || pendingTurnId != nil
    }

    func clearSession() {
        guard !inputLocked else { return }
        intentJourney.clear()
        turns = []
        pendingTurnId = nil
        lastResponse = ""
        historyNotice = ""
        historyNextBeforeId = nil
        historyExhausted = false
        skipScrollToLatest = false
    }

    func sendIntent(text: String, source: String, serverURL: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !inputLocked else { return }

        intentServerURL = serverURL
        intentClient.lastServerURL = serverURL
        await ensureRegistered(serverURL: serverURL)

        let turn = ChatTurn(
            id: UUID(),
            intentId: "",
            createdAt: Date(),
            userText: trimmed,
            source: source,
            journey: IntentJourney.make(jobId: "pending…", text: trimmed, status: .uploaded),
            assistantText: nil,
            awaitingTerminal: true
        )
        turns.append(turn)
        pendingTurnId = turn.id
        sending = true
        defer { sending = false }

        intentJourney.startOptimistic(text: trimmed)

        let result = await intentClient.dispatch(
            text: trimmed,
            source: source,
            serverURL: serverURL
        )
        lastResponse = result.message

        guard result.ok, let snapshot = result.snapshot else {
            intentJourney.markLegacyServerMissingJob(
                detail: result.message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "发出失败"
                    : String(result.message.prefix(200))
            )
            return
        }

        intentJourney.startFromPost(snapshot)
        if let idx = turns.firstIndex(where: { $0.id == turn.id }) {
            turns[idx].intentId = snapshot.jobId
        }
        let url = serverURL
        intentJourney.startPolling(jobId: snapshot.jobId) { [weak self] jobId in
            await self?.intentClient.fetchIntentDetail(intentId: jobId, intentURL: url)
        }
    }

    func journey(for turnId: UUID) -> IntentJourney? {
        turns.first(where: { $0.id == turnId })?.journey
    }

    private func syncPendingTurn(with journey: IntentJourney?) {
        guard let id = pendingTurnId,
              let idx = turns.firstIndex(where: { $0.id == id }) else { return }
        guard let journey else { return }

        turns[idx].journey = journey
        let finished = journey.terminal || journey.timedOut
        guard finished else { return }

        turns[idx].assistantText = ChatTurn.assistantText(for: journey)
        turns[idx].awaitingTerminal = false
        pendingTurnId = nil
    }

    func loadOlderHistory(serverURL: String) async {
        let url = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }

        await ensureRegistered(serverURL: url)
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            historyNotice = "尚未登记 participant，无法拉历史"
            return
        }

        if historyExhausted {
            historyNotice = "没有更早的本机历史"
            return
        }

        let oldestShown = turns.compactMap { Int($0.intentId) }.min()
        let before: Int?
        if let scanned = historyNextBeforeId {
            before = scanned
        } else if let oldestShown {
            before = oldestShown
        } else {
            before = nil
        }

        let wasEmpty = turns.isEmpty
        let page = await intentClient.fetchIssuerHistory(
            participantId: pid,
            beforeId: before,
            intentURL: url,
            limit: IntentClient.historyPageLimit
        )
        historyNextBeforeId = page.nextBeforeId
        if page.exhausted {
            historyExhausted = true
        }

        let existing = Set(turns.map(\.intentId).filter { !$0.isEmpty })
        let incoming = page.snapshots
            .filter { !existing.contains($0.jobId) }
            .map { ChatTurn.fromHistory($0) }

        if incoming.isEmpty {
            historyNotice = historyExhausted ? "没有更早的本机历史" : "这一页没有本机记录，可再下拉"
            return
        }

        historyNotice = ""
        skipScrollToLatest = !wasEmpty
        turns = Self.sortedTurns(incoming + turns)
        resumePollingIfNeeded(serverURL: url)
    }

    func consumeSkipScrollToLatest() -> Bool {
        let skip = skipScrollToLatest
        skipScrollToLatest = false
        return skip
    }

    private static func sortedTurns(_ items: [ChatTurn]) -> [ChatTurn] {
        items.sorted { a, b in
            if a.createdAt != b.createdAt { return a.createdAt < b.createdAt }
            let ai = Int(a.intentId) ?? Int.max
            let bi = Int(b.intentId) ?? Int.max
            return ai < bi
        }
    }

    private func resumePollingIfNeeded(serverURL: String) {
        guard pendingTurnId == nil else { return }
        guard let turn = turns.last(where: { $0.awaitingTerminal && !$0.intentId.isEmpty }) else {
            return
        }
        pendingTurnId = turn.id
        intentJourney.adopt(turn.journey)
        let url = serverURL
        intentJourney.startPolling(jobId: turn.intentId) { [weak self] jobId in
            await self?.intentClient.fetchIntentDetail(intentId: jobId, intentURL: url)
        }
    }

    func ensureRegistered(serverURL: String, force: Bool = false) async {
        let url = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        let known = ParticipantStore.participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !force, !known.isEmpty, ParticipantStore.lastRegisteredBrainURL == url {
            participantId = known
            clientHint = ParticipantStore.clientHint
            return
        }
        guard let pid = await intentClient.registerParticipant(serverURL: url) else {
            clientHint = ParticipantStore.clientHint
            return
        }
        ParticipantStore.participantId = pid
        ParticipantStore.lastRegisteredBrainURL = url
        participantId = pid
        clientHint = ParticipantStore.clientHint
    }
}
