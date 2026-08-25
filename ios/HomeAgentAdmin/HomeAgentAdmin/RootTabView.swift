import SwiftUI
import UIKit

struct RootTabView: View {
    @EnvironmentObject private var store: AdminStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: AdminTab = .nodes

    enum AdminTab: Hashable {
        case nodes
        case events
        case manage
        case connection
    }

    var body: some View {
        TabView(selection: $tab) {
            NodeListView()
                .tabItem {
                    Label("节点", systemImage: "point.3.connected.trianglepath.dotted")
                }
                .tag(AdminTab.nodes)

            EventStreamView()
                .tabItem {
                    Label("事件流", systemImage: "bolt.horizontal")
                }
                .tag(AdminTab.events)

            ManagementLogView()
                .tabItem {
                    Label("管理", systemImage: "list.bullet.rectangle")
                }
                .tag(AdminTab.manage)

            ConnectionView()
                .tabItem {
                    Label("连接", systemImage: "link")
                }
                .tag(AdminTab.connection)
        }
        .tint(AdminTheme.sand)
        .background(AdminTheme.ink.ignoresSafeArea())
        .task {
            await store.load(showSpinner: true)
        }
        .onChange(of: scenePhase) { phase in
            syncPolling(phase: phase, tab: tab)
            if phase == .active, tab == .nodes {
                Task { await store.load(showSpinner: false) }
            }
            if phase == .active, tab == .events {
                Task { await store.loadIntents(reset: true, showSpinner: false) }
            }
        }
        .onChange(of: tab) { next in
            syncPolling(phase: scenePhase, tab: next)
        }
        .onAppear {
            syncPolling(phase: scenePhase, tab: tab)
        }
        .onDisappear {
            store.stopPolling()
            store.stopIntentPolling()
        }
    }

    private func syncPolling(phase: ScenePhase, tab: AdminTab) {
        store.stopPolling()
        store.stopIntentPolling()
        guard phase == .active else { return }
        if tab == .nodes {
            store.startPolling()
        } else if tab == .events {
            store.startIntentPolling()
        }
    }

    private static var didConfigureTabBar = false

    static func configureTabBarAppearanceOnce() {
        guard !didConfigureTabBar else { return }
        didConfigureTabBar = true
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(AdminTheme.ink)
        let item = UITabBarItemAppearance()
        let muted = UIColor(white: 1, alpha: 0.38)
        let active = UIColor(AdminTheme.sand)
        item.normal.iconColor = muted
        item.normal.titleTextAttributes = [.foregroundColor: muted]
        item.selected.iconColor = active
        item.selected.titleTextAttributes = [.foregroundColor: active]
        appearance.stackedLayoutAppearance = item
        appearance.inlineLayoutAppearance = item
        appearance.compactInlineLayoutAppearance = item
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }
}
