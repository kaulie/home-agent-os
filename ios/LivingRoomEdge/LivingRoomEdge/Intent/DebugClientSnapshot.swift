import Foundation

/// User Console execution现场 extras for `POST /api/v1/debug/report`.
enum DebugClientSnapshot {
    static func build(
        env: BrainNetworkEnvironment,
        intentServerURL: String,
        lanHeartbeat: BrainHeartbeatStatus,
        cloudHeartbeat: BrainHeartbeatStatus,
        clientHint: String,
        journey: IntentJourney,
        intentId: String
    ) -> [String: Any] {
        let primary = env.mode
        var snapshot: [String: Any] = [
            "primary_brain": [
                "mode": primary.rawValue,
                "mode_label": env.modeLabel,
                "routing": env.routing.rawValue,
                "routing_label": env.routingLabel,
                "base_url": env.activeBaseURL,
                "intent_url": intentServerURL,
                "path_kind": env.pathKind.rawValue,
                "looks_on_home_lan": env.looksOnHomeLAN,
            ],
            "heartbeat": [
                "primary_mode": primary.rawValue,
                "lan": heartbeatDictionary(lanHeartbeat),
                "cloud": heartbeatDictionary(cloudHeartbeat),
            ],
            "runtime_intent_log": runtimeIntentLog(journey: journey, intentId: intentId),
            "journey_phase": journey.current.rawValue,
            "journey_error": journey.error ?? "",
            "brain_mode": env.modeLabel,
            "brain_routing": env.routingLabel,
            "brain_base": env.activeBaseURL,
            "client_hint": clientHint,
        ]
        return snapshot
    }

    private static func heartbeatDictionary(_ status: BrainHeartbeatStatus) -> [String: Any] {
        var row: [String: Any] = [
            "mode": status.mode.rawValue,
            "registered": status.registered,
            "last_ok": status.lastOk,
            "last_error": status.lastError,
            "phase": heartbeatPhaseLabel(status.phase),
        ]
        if let registeredAt = status.registeredAt {
            row["registered_at"] = isoString(registeredAt)
        }
        if let lastAttemptAt = status.lastAttemptAt {
            row["last_attempt_at"] = isoString(lastAttemptAt)
        }
        if let lastSuccessAt = status.lastSuccessAt {
            row["last_success_at"] = isoString(lastSuccessAt)
        }
        return row
    }

    private static func heartbeatPhaseLabel(_ phase: HeartbeatPhase) -> String {
        switch phase {
        case .idle: return "idle"
        case .sending: return "sending"
        case .retrying(let attempt): return "retrying_\(attempt)"
        }
    }

    private static func runtimeIntentLog(journey: IntentJourney, intentId: String) -> [String: Any] {
        var log: [String: Any] = [:]
        if let cached = JourneyLocalCache.snapshotDictionary(intentId) {
            log["local_journey_cache"] = cached
        }
        if !journey.planSteps.isEmpty {
            log["plan_steps"] = journey.planSteps.map { step in
                [
                    "step": step.step,
                    "capability": step.capability,
                    "status": step.runStatus.label,
                    "detail": step.runDetail,
                    "assigned_edge": step.assignedEdge,
                ] as [String: Any]
            }
        }
        if !journey.phases.isEmpty {
            log["phases"] = journey.phases.map { phase in
                var row: [String: Any] = [
                    "phase": phase.phase.rawValue,
                    "detail": phase.detail,
                ]
                if let at = phase.at {
                    row["at"] = isoString(at)
                }
                return row
            }
        }
        if log.isEmpty {
            log["note"] = "no local runtime log for this intent"
        }
        return log
    }

    private static func isoString(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}
