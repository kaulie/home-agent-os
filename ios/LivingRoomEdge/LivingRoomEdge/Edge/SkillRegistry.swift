import Foundation

final class SkillRegistry {
    private var skills: [String: Skill] = [:]

    func register(_ skill: Skill) {
        skills[skill.service().serviceId] = skill
    }

    func registerAll(_ items: [Skill]) {
        items.forEach { register($0) }
    }

    /// Replace entire skill map (used when rebuilding from Capability plugins).
    func replaceAll(_ items: [Skill]) {
        skills.removeAll(keepingCapacity: true)
        registerAll(items)
    }

    func get(_ skillId: String) -> Skill? {
        skills[skillId]
    }

    func findByCapability(_ capabilityId: String) -> (Skill, ServiceDescriptor)? {
        let want = capabilityId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !want.isEmpty else { return nil }
        for skill in skills.values {
            let svc = skill.service()
            if svc.capabilities.contains(where: { $0.capabilityId == want }) {
                return (skill, svc)
            }
        }
        return nil
    }

    func all() -> [Skill] {
        Array(skills.values)
    }

    func services() -> [ServiceDescriptor] {
        skills.values.map { $0.service() }.sorted { $0.serviceId < $1.serviceId }
    }
}
