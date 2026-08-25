import SwiftUI

/// Entity browser: top tabs by Entity type (V1: device only).
struct EntityBrowserView: View {
    @State private var entityType: EntityTypeTab = .device

    /// Supported Entity types for the top switcher. Extend when Registry grows.
    enum EntityTypeTab: String, CaseIterable, Identifiable, Hashable {
        case device

        var id: String { rawValue }

        var title: String {
            switch self {
            case .device: return "Device"
            }
        }

        var subtitle: String {
            switch self {
            case .device: return "物理设备"
            }
        }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                EdgeTheme.canvas
                VStack(spacing: 0) {
                    entityTypeSwitcher
                    Divider().overlay(EdgeTheme.panelStroke)
                    Group {
                        switch entityType {
                        case .device:
                            DeviceEntitiesPage()
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("实体")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
            }
            .toolbarBackground(EdgeTheme.ink, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private var entityTypeSwitcher: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(EntityTypeTab.allCases) { type in
                    Button {
                        withAnimation(.easeOut(duration: 0.18)) {
                            entityType = type
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(type.title)
                                .font(.system(size: 14, weight: .semibold, design: .rounded))
                            Text(type.subtitle)
                                .font(.system(size: 11, weight: .regular, design: .rounded))
                                .opacity(0.75)
                        }
                        .foregroundStyle(entityType == type ? EdgeTheme.ink : EdgeTheme.mist)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(entityType == type ? EdgeTheme.sand : Color.white.opacity(0.06))
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(type.title)
                    .accessibilityAddTraits(entityType == type ? .isSelected : [])
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(EdgeTheme.ink.opacity(0.92))
    }
}

/// Device Entity list for this node (local catalog until Brain Entity Registry exists).
private struct DeviceEntitiesPage: View {
    @EnvironmentObject private var model: AppModel

    private var devices: [LocalDeviceEntity] {
        LocalDeviceEntity.fromAdvertised(
            services: ParticipantStore.advertisedServices(roles: model.enabledRoles)
        )
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    EdgeTheme.heroTitle("Device")
                    EdgeTheme.heroSubtitle(
                        "Device 是 Entity 的一种。以下为本节点当前会广告的设备实体（本地视图；Brain Entity Registry 未点名不接入）。"
                    )
                }
                .padding(.top, 8)

                HStack(spacing: 10) {
                    Circle()
                        .fill(devices.isEmpty ? EdgeTheme.dim : Color.green.opacity(0.85))
                        .frame(width: 8, height: 8)
                    Text(devices.isEmpty ? "暂无 Device 实体" : "\(devices.count) 台 Device")
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }

                if devices.isEmpty {
                    EdgeEmptyPlaceholder(
                        title: "无 Device",
                        detail: "开启 runtime（并配置空调账号等）后，本机广告的服务会映射为 Device 实体出现在此。"
                    )
                } else {
                    VStack(alignment: .leading, spacing: 12) {
                        EdgeTheme.sectionLabel("实体列表")
                        ForEach(devices) { device in
                            deviceCard(device)
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 36)
        }
    }

    private func deviceCard(_ device: LocalDeviceEntity) -> some View {
        EdgePanel {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(device.name)
                        .font(.system(size: 18, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.white.opacity(0.94))
                    Spacer(minLength: 8)
                    Text("device")
                        .font(.system(size: 11, weight: .semibold, design: .rounded))
                        .tracking(0.8)
                        .foregroundStyle(EdgeTheme.sand)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.white.opacity(0.06))
                        .clipShape(Capsule())
                }
                Text(device.id)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(EdgeTheme.dim)
                    .textSelection(.enabled)
                if !device.serviceId.isEmpty {
                    Text("service · \(device.serviceId)")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
                if !device.capabilityIds.isEmpty {
                    Text(device.capabilityIds.joined(separator: " · "))
                        .font(.system(size: 12, weight: .regular, design: .monospaced))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
    }
}

struct LocalDeviceEntity: Identifiable, Equatable {
    let id: String
    let name: String
    let serviceId: String
    let capabilityIds: [String]

    static func fromAdvertised(services: [[String: Any]]) -> [LocalDeviceEntity] {
        var out: [LocalDeviceEntity] = []
        for svc in services {
            let serviceId = (svc["service_id"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !serviceId.isEmpty else { continue }
            let name = (svc["display_name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let caps = svc["capabilities"] as? [[String: Any]] ?? []
            let capIds = caps.compactMap { ($0["capability_id"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            out.append(
                LocalDeviceEntity(
                    id: "device.\(serviceId)",
                    name: (name?.isEmpty == false ? name! : serviceId),
                    serviceId: serviceId,
                    capabilityIds: capIds
                )
            )
        }
        return out
    }
}
