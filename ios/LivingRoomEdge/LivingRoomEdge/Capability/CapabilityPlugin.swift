import Foundation

/// A capability plugin installed **on the Edge node** (local plugin registration).
///
/// Brain discovery is via `BrainClient.reportEdgeInfo` with `services[]`.
/// Plugins contribute Skills; each Skill exposes `service()` for the wire contract.
protocol CapabilityPlugin: AnyObject {
    /// Plugin / service key, e.g. `gopro.camera`.
    var capabilityId: String { get }
    /// Human-readable description for local UI.
    var description: String { get }
    var version: String { get }
    /// Skills this plugin contributes when registered on the edge.
    func makeSkills() -> [Skill]
}

/// Edge-local registry: Capability plugins register here; skills are derived from plugins.
final class CapabilityRegistry {
    private var plugins: [String: CapabilityPlugin] = [:]

    @discardableResult
    func register(_ plugin: CapabilityPlugin) -> Bool {
        let id = plugin.capabilityId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return false }
        plugins[id] = plugin
        return true
    }

    func registerAll(_ items: [CapabilityPlugin]) {
        items.forEach { register($0) }
    }

    func unregister(_ capabilityId: String) {
        plugins.removeValue(forKey: capabilityId)
    }

    func get(_ capabilityId: String) -> CapabilityPlugin? {
        plugins[capabilityId]
    }

    func all() -> [CapabilityPlugin] {
        plugins.values.sorted { $0.capabilityId < $1.capabilityId }
    }

    func capabilityIds() -> [String] {
        all().map(\.capabilityId)
    }

    /// Services for edge → brain report.
    func services() -> [ServiceDescriptor] {
        makeSkills().map { $0.service() }.sorted { $0.serviceId < $1.serviceId }
    }

    /// Flatten skills from all registered capability plugins (dedupe by serviceId).
    func makeSkills() -> [Skill] {
        var seen: Set<String> = []
        var out: [Skill] = []
        for plugin in all() {
            for skill in plugin.makeSkills() {
                let id = skill.service().serviceId
                if seen.insert(id).inserted {
                    out.append(skill)
                }
            }
        }
        return out
    }
}
