import Foundation

/// Edge plugin that installs NetEaseMusicSkill (service netease.music / group music).
final class NetEaseMusicCapabilityPlugin: CapabilityPlugin {
    let capabilityId = NetEaseMusicSkill.skillId
    let description = "网易云音乐播放"
    let version = "0.3.0"

    private let skill: NetEaseMusicSkill

    init(skill: NetEaseMusicSkill = NetEaseMusicSkill()) {
        self.skill = skill
    }

    func makeSkills() -> [Skill] {
        [skill]
    }
}
