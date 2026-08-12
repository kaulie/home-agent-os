import Foundation

/// Edge capability plugin: `intent.dispatch` → IntentSkill.
final class IntentDispatchCapabilityPlugin: CapabilityPlugin {
    let capabilityId = Capabilities.intentDispatch
    let description = Capabilities.describe(Capabilities.intentDispatch)
    let version = "0.1.0"

    private let controller: IntentController

    init(controller: IntentController) {
        self.controller = controller
    }

    func makeSkills() -> [Skill] {
        [IntentSkill(controller: controller)]
    }
}

/// Edge capability plugin: `commands.pull` → CommandSkill.
final class CommandPullCapabilityPlugin: CapabilityPlugin {
    let capabilityId = Capabilities.commandsPull
    let description = Capabilities.describe(Capabilities.commandsPull)
    let version = "0.1.0"

    private let controller: CommandController

    init(controller: CommandController) {
        self.controller = controller
    }

    func makeSkills() -> [Skill] {
        [CommandSkill(controller: controller)]
    }
}
