import SwiftUI

/// Read-only catalog of capabilities this node advertises when runtime is enabled.
struct RuntimeCapabilitiesView: View {
    @EnvironmentObject private var model: AppModel

    private var rows: [AdvertisedCapabilityRow] {
        AdvertisedCapabilityRow.from(services: ParticipantStore.advertisedServices(roles: model.enabledRoles))
    }

    private var runtimeOn: Bool {
        model.enabledRoles.contains("runtime")
    }

    var body: some View {
        NavigationStack {
            ZStack {
                EdgeTheme.canvas
                ScrollView {
                    VStack(alignment: .leading, spacing: 28) {
                        VStack(alignment: .leading, spacing: 8) {
                            EdgeTheme.heroTitle("能力")
                            EdgeTheme.heroSubtitle(
                                runtimeOn
                                    ? "本节点作为 Runtime 向下属能力做只读展示，不在此发起实质调用。"
                                    : "未启用 runtime role，当前不会向 Brain 广告任何能力。可在「节点」页开启。"
                            )
                        }
                        .padding(.top, 8)

                        HStack(spacing: 10) {
                            Circle()
                                .fill(runtimeOn ? Color.green.opacity(0.85) : EdgeTheme.dim)
                                .frame(width: 8, height: 8)
                            Text(runtimeOn ? "runtime 已启用 · \(rows.count) 项能力" : "runtime 未启用")
                                .font(.system(size: 13, weight: .medium, design: .rounded))
                                .foregroundStyle(EdgeTheme.mist)
                        }

                        if rows.isEmpty {
                            EdgeEmptyPlaceholder(
                                title: "暂无下属能力",
                                detail: "开启 runtime 后，将列出本机广告的 capability（如 camera.capture、light.set、document.scan、video.live_stream）。"
                            )
                        } else {
                            VStack(alignment: .leading, spacing: 12) {
                                EdgeTheme.sectionLabel("下属能力")
                                ForEach(rows) { row in
                                    capabilityCard(row)
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 36)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("能力")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
            }
            .toolbarBackground(EdgeTheme.ink, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private func capabilityCard(_ row: AdvertisedCapabilityRow) -> some View {
        EdgePanel {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(row.capabilityId)
                        .font(.system(size: 17, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.white.opacity(0.94))
                    Spacer(minLength: 8)
                    Text(row.serviceName)
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(EdgeTheme.sand)
                }
                if !row.role.isEmpty {
                    Text(row.role)
                        .font(.system(size: 14, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
                if !row.plannerRecognize.isEmpty {
                    Text(row.plannerRecognize)
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
                if !row.triggers.isEmpty {
                    Text(row.triggers.joined(separator: " · "))
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
    }
}

struct AdvertisedCapabilityRow: Identifiable, Equatable {
    var id: String { "\(serviceId)/\(capabilityId)" }
    let serviceId: String
    let serviceName: String
    let capabilityId: String
    let role: String
    let plannerRecognize: String
    let triggers: [String]

    static func from(services: [[String: Any]]) -> [AdvertisedCapabilityRow] {
        var out: [AdvertisedCapabilityRow] = []
        for svc in services {
            let serviceId = (svc["service_id"] as? String) ?? ""
            let serviceName = (svc["display_name"] as? String) ?? serviceId
            let caps = svc["capabilities"] as? [[String: Any]] ?? []
            for cap in caps {
                let cid = (cap["capability_id"] as? String) ?? ""
                guard !cid.isEmpty else { continue }
                out.append(
                    AdvertisedCapabilityRow(
                        serviceId: serviceId,
                        serviceName: serviceName,
                        capabilityId: cid,
                        role: (cap["role"] as? String) ?? "",
                        plannerRecognize: (cap["planner_recognize"] as? String) ?? "",
                        triggers: (cap["typical_triggers"] as? [String]) ?? []
                    )
                )
            }
        }
        return out
    }
}
