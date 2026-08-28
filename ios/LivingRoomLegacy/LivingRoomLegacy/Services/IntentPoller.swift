import Foundation

protocol IntentPollerDelegate: AnyObject {
    func poller(_ poller: IntentPoller, didUpdate snapshot: IntentDetailSnapshot)
    func poller(_ poller: IntentPoller, didFail intentId: String, error: String)
}

final class IntentPoller {
    weak var delegate: IntentPollerDelegate?

    private var timer: Timer?
    private var intentURL: String = ""
    private var intentId: String = ""

    func start(intentURL: String, intentId: String) {
        stop()
        self.intentURL = intentURL
        self.intentId = intentId
        pollOnce()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.pollOnce()
        }
        if let timer = timer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        intentId = ""
    }

    private func pollOnce() {
        let iid = intentId
        guard !iid.isEmpty else { return }
        BrainAPI.fetchIntentDetail(intentURL: intentURL, intentId: iid) { [weak self] result in
            guard let self = self, self.intentId == iid else { return }
            switch result {
            case .failure(let err):
                self.delegate?.poller(self, didFail: iid, error: err.message)
            case .success(let snap):
                self.delegate?.poller(self, didUpdate: snap)
                if isTerminalStatus(snap.status) {
                    self.stop()
                }
            }
        }
    }

    private func isTerminalStatus(_ status: String) -> Bool {
        let s = status.lowercased()
        return s == "succeeded" || s == "failed" || s == "error" || s == "cancelled"
    }
}
