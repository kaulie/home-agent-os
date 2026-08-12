import Foundation

/// Blocks rapid re-taps / double-clicks on action buttons.
@MainActor
final class ClickGuard: ObservableObject {
    /// True while an async action holds the gate (optional UX).
    @Published private(set) var held = false

    private var cooldownUntil: Date = .distantPast
    private let defaultCooldown: TimeInterval

    init(defaultCooldown: TimeInterval = 0.8) {
        self.defaultCooldown = defaultCooldown
    }

    /// Returns true if this tap may proceed; starts cooldown immediately.
    @discardableResult
    func tryTap(cooldown: TimeInterval? = nil) -> Bool {
        let now = Date()
        if now < cooldownUntil { return false }
        cooldownUntil = now.addingTimeInterval(cooldown ?? defaultCooldown)
        return true
    }

    /// Like `tryTap`, and marks `held` until `releaseHold()` (for long-running ops).
    @discardableResult
    func tryHold(cooldown: TimeInterval? = nil) -> Bool {
        guard tryTap(cooldown: cooldown) else { return false }
        held = true
        return true
    }

    func releaseHold() {
        held = false
    }
}
