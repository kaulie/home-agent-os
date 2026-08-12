import Foundation

/// Map server intent `execution_plan[].capability` → local EdgeTask.
/// Mirrors Android `CommandDecomposer`.
/// Install matrix: iPhone = GoPro (+ local system helpers); NetEase not installed.
enum CommandDecomposer {
    static func fromServerCommand(_ cmd: EdgeCommand) -> [EdgeTask] {
        let mapped = mapCapability(cmd)
        return [
            EdgeTask(
                taskId: "task-\(cmd.commandId)-\(UUID().uuidString.prefix(6))",
                commandId: cmd.commandId,
                skillId: mapped.skillId,
                action: mapped.capabilityId,
                params: mapped.params,
                schedule: cmd.schedule,
                targetHint: mapped.capabilityId,
                skipReason: mapped.skipReason,
                outputConstrict: cmd.outputConstrict
            ),
        ]
    }

    static func fromPlan(_ plan: Plan) -> [EdgeCommand] {
        plan.steps.map { step in
            EdgeCommand(
                commandId: "\(plan.planId)/\(step.stepId)",
                device: step.skillId,
                action: step.action,
                params: step.params,
                schedule: .instant,
                source: .mockPlan,
                raw: [
                    "planId": plan.planId,
                    "stepId": step.stepId,
                    "skillId": step.skillId,
                ]
            )
        }
    }

    static func planCommandsToTasks(_ commands: [EdgeCommand]) -> [EdgeTask] {
        commands.map { cmd in
            let skillId = (cmd.raw["skillId"] as? String) ?? cmd.device
            return EdgeTask(
                taskId: "task-\(cmd.commandId)",
                commandId: cmd.commandId,
                skillId: skillId,
                action: cmd.action,
                params: cmd.params,
                schedule: cmd.schedule,
                targetHint: nil,
                skipReason: nil,
                outputConstrict: cmd.outputConstrict
            )
        }
    }

    private struct Mapped {
        let skillId: String?
        let capabilityId: String
        let params: [String: String]
        let skipReason: String?
    }

    private static func mapCapability(_ cmd: EdgeCommand) -> Mapped {
        let capability = resolveCapabilityId(cmd)
        guard !capability.isEmpty else {
            return Mapped(
                skillId: nil,
                capabilityId: "",
                params: cmd.params,
                skipReason: "missing capability_id"
            )
        }
        if Capabilities.cameraAll.contains(capability) {
            return Mapped(
                skillId: GoProSkill.skillId,
                capabilityId: capability,
                params: cmd.params,
                skipReason: nil
            )
        }
        if Capabilities.musicAll.contains(capability) {
            var params = normalizeMusicParams(capability, cmd.params)
            params["capability"] = capability
            return Mapped(
                skillId: nil,
                capabilityId: capability,
                params: params,
                skipReason: "netease.music not installed on iphone"
            )
        }
        if Capabilities.displayAll.contains(capability) {
            return Mapped(
                skillId: ChromecastCastSkill.skillId,
                capabilityId: capability,
                params: cmd.params,
                skipReason: nil
            )
        }
        if Capabilities.bluetoothAll.contains(capability) {
            return Mapped(
                skillId: nil,
                capabilityId: capability,
                params: cmd.params,
                skipReason: "marshall.willen not installed on iphone"
            )
        }
        switch capability {
        case Capabilities.commandsPull, Capabilities.commandsExecute:
            return Mapped(
                skillId: CommandSkill.skillId,
                capabilityId: capability,
                params: cmd.params,
                skipReason: nil
            )
        case Capabilities.intentDispatch:
            return Mapped(
                skillId: IntentSkill.skillId,
                capabilityId: capability,
                params: cmd.params,
                skipReason: nil
            )
        default:
            return Mapped(
                skillId: nil,
                capabilityId: capability,
                params: cmd.params,
                skipReason: "unsupported capability: '\(capability)'"
            )
        }
    }

    private static func resolveCapabilityId(_ cmd: EdgeCommand) -> String {
        let raw: String
        if let fromParams = cmd.params["capability"]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !fromParams.isEmpty {
            raw = fromParams
        } else {
            let device = cmd.device.trimmingCharacters(in: .whitespacesAndNewlines)
            raw = !device.isEmpty
                ? device
                : cmd.action.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return raw
    }

    /// Canonical wire fields only: song / artist / album.
    private static func normalizeMusicParams(
        _ capability: String,
        _ params: [String: String]
    ) -> [String: String] {
        guard capability == Capabilities.musicPlay else { return params }
        var out = params
        let song = out["song"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let artist = out["artist"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let album = out["album"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !song.isEmpty { out["song"] = song } else { out.removeValue(forKey: "song") }
        if !artist.isEmpty { out["artist"] = artist } else { out.removeValue(forKey: "artist") }
        if !album.isEmpty { out["album"] = album } else { out.removeValue(forKey: "album") }
        return out
    }
}
