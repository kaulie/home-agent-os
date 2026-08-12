import Foundation

/// Plugin entry for Edge UI / AppModel — mirrors GoProPluginEntry pattern.
final class NetEasePluginEntry {
    static let skillId = NetEaseMusicSkill.skillId

    private let skill: NetEaseMusicSkill

    init(skill: NetEaseMusicSkill = NetEaseMusicSkill()) {
        self.skill = skill
    }

    func makeCapabilityPlugin() -> CapabilityPlugin {
        NetEaseMusicCapabilityPlugin(skill: skill)
    }

    func invoke(capabilityId: String, params: [String: String]) async -> SkillResult {
        await skill.execute(
            capabilityId: capabilityId,
            params: params,
            context: SkillContext(edgeId: "local", planId: "ui", stepId: "0")
        )
    }
}
