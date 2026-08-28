import Foundation

struct DeployPipelineNode: Decodable, Equatable, Identifiable {
    var id: String { node }
    let node: String
    let done: Bool
}

struct DeployStageEvent: Decodable, Equatable, Identifiable {
    var id: String { "\(stage)-\(at?.timeIntervalSince1970 ?? 0)-\(by)" }
    let stage: String
    let at: Date?
    let by: String
    let result: String
    let note: String

    enum CodingKeys: String, CodingKey {
        case stage, at, by, result, note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stage = try c.decodeIfPresent(String.self, forKey: .stage) ?? ""
        at = WireTime.decode(c, key: .at)
        by = try c.decodeIfPresent(String.self, forKey: .by) ?? ""
        result = try c.decodeIfPresent(String.self, forKey: .result) ?? ""
        note = try c.decodeIfPresent(String.self, forKey: .note) ?? ""
    }
}

struct DeployRelease: Identifiable, Decodable, Equatable {
    var id: Int { releaseId }
    let releaseId: Int
    let sha: String
    let shaShort: String
    let scope: String
    let summary: String
    let target: String
    let status: String
    let stages: [DeployStageEvent]
    let pipeline: [DeployPipelineNode]
    let updatedAt: Date?
    let approvedBy: String
    let deployRunId: String
    let canApprove: Bool
    let canReject: Bool
    let rejectNote: String

    enum CodingKeys: String, CodingKey {
        case releaseId = "release_id"
        case sha
        case shaShort = "sha_short"
        case scope, summary, target, status, stages, pipeline
        case updatedAt = "updated_at"
        case approvedBy = "approved_by"
        case deployRunId = "deploy_run_id"
        case canApprove = "can_approve"
        case canReject = "can_reject"
        case rejectNote = "reject_note"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        releaseId = try c.decode(Int.self, forKey: .releaseId)
        sha = try c.decodeIfPresent(String.self, forKey: .sha) ?? ""
        shaShort = try c.decodeIfPresent(String.self, forKey: .shaShort) ?? String(sha.prefix(7))
        scope = try c.decodeIfPresent(String.self, forKey: .scope) ?? ""
        summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        target = try c.decodeIfPresent(String.self, forKey: .target) ?? "cloud-brain"
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        stages = try c.decodeIfPresent([DeployStageEvent].self, forKey: .stages) ?? []
        pipeline = try c.decodeIfPresent([DeployPipelineNode].self, forKey: .pipeline) ?? []
        updatedAt = WireTime.decode(c, key: .updatedAt)
        approvedBy = try c.decodeIfPresent(String.self, forKey: .approvedBy) ?? ""
        deployRunId = try c.decodeIfPresent(String.self, forKey: .deployRunId) ?? ""
        canApprove = try c.decodeIfPresent(Bool.self, forKey: .canApprove) ?? false
        canReject = try c.decodeIfPresent(Bool.self, forKey: .canReject) ?? false
        rejectNote = try c.decodeIfPresent(String.self, forKey: .rejectNote) ?? ""
    }

    var statusLabel: String {
        switch status {
        case "awaiting_approval": return "待批准"
        case "in_progress": return "进行中"
        case "approved": return "已批准"
        case "deploying": return "部署中"
        case "deployed": return "已上线"
        case "test_failed": return "测试失败"
        case "rejected": return "已拒绝"
        case "skipped": return "已跳过"
        default: return status
        }
    }
}

struct DeployCounts: Decodable, Equatable {
    let awaitingApproval: Int
    let inFlight: Int
    let total: Int

    enum CodingKeys: String, CodingKey {
        case awaitingApproval = "awaiting_approval"
        case inFlight = "in_flight"
        case total
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        awaitingApproval = try c.decodeIfPresent(Int.self, forKey: .awaitingApproval) ?? 0
        inFlight = try c.decodeIfPresent(Int.self, forKey: .inFlight) ?? 0
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
    }
}

struct DeploySnapshot: Decodable, Equatable {
    let ok: Bool?
    let error: String?
    let releases: [DeployRelease]
    let counts: DeployCounts?
    let pipelineNodes: [String]

    enum CodingKeys: String, CodingKey {
        case ok, error, releases, counts
        case pipelineNodes = "pipeline_nodes"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        releases = try c.decodeIfPresent([DeployRelease].self, forKey: .releases) ?? []
        counts = try c.decodeIfPresent(DeployCounts.self, forKey: .counts)
        pipelineNodes = try c.decodeIfPresent([String].self, forKey: .pipelineNodes)
            ?? ["committed", "tested", "approved", "deployed"]
    }
}

struct DeployActionResponse: Decodable {
    let ok: Bool?
    let error: String?
    let release: DeployRelease?
}
