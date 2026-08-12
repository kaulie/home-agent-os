import Foundation

struct SkillContext {
    let edgeId: String
    let planId: String
    let stepId: String
}

struct SkillResult {
    let ok: Bool
    let message: String?
    let outputs: [String: String]?

    static func ok(_ message: String? = nil, outputs: [String: String]? = nil) -> SkillResult {
        SkillResult(ok: true, message: message, outputs: outputs)
    }

    static func error(_ message: String) -> SkillResult {
        SkillResult(ok: false, message: message, outputs: nil)
    }
}

protocol Skill: AnyObject {
    /// Wire contract: Service → Capability (schemas).
    func service() -> ServiceDescriptor
    /// Invoke by capability_id (local debug may also pass legacy action names).
    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult
}
