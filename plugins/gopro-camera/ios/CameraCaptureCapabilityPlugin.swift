import Foundation

/// Edge plugin that installs GoProSkill (service gopro.camera / group camera).
final class CameraCaptureCapabilityPlugin: CapabilityPlugin {
    let capabilityId = GoProSkill.skillId
    let description = "GoPro 相机拍照 / 录像"
    let version = "0.1.0"

    private let controller: GoProController

    init(controller: GoProController) {
        self.controller = controller
    }

    func makeSkills() -> [Skill] {
        [GoProSkill(controller: controller)]
    }
}
