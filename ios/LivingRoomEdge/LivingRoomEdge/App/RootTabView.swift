import SwiftUI
import UIKit

/// Five-pane shell: 互动 · 系统 · 能力 · 实体 · 节点
struct RootTabView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: EdgeTab = .chat

    enum EdgeTab: Hashable {
        case chat
        case game
        case system
        case runtime
        case entity
        case node
    }

    var body: some View {
        TabView(selection: $tab) {
            ContentView()
                .tabItem {
                    Label("互动", systemImage: "bubble.left.and.bubble.right.fill")
                }
                .tag(EdgeTab.chat)

            GameControllerView()
                .tabItem {
                    Label("游戏", systemImage: "gamecontroller.fill")
                }
                .tag(EdgeTab.game)

            SystemObserverView()
                .tabItem {
                    Label("系统", systemImage: "antenna.radiowaves.left.and.right")
                }
                .tag(EdgeTab.system)

            RuntimeCapabilitiesView()
                .tabItem {
                    Label("能力", systemImage: "square.stack.3d.up.fill")
                }
                .tag(EdgeTab.runtime)

            EntityBrowserView()
                .tabItem {
                    Label("实体", systemImage: "shippingbox")
                }
                .tag(EdgeTab.entity)

            NodeInfoView()
                .tabItem {
                    Label("节点", systemImage: "point.3.connected.trianglepath.dotted")
                }
                .tag(EdgeTab.node)
        }
        .tint(EdgeTheme.sand)
        .background(EdgeTheme.ink.ignoresSafeArea())
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.onForeground()
            }
        }
    }

    private static var didConfigureTabBar = false

    /// Call from `LivingRoomEdgeApp.init` before first frame.
    static func configureTabBarAppearanceOnce() {
        guard !didConfigureTabBar else { return }
        didConfigureTabBar = true
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(EdgeTheme.ink)
        let item = UITabBarItemAppearance()
        let muted = UIColor(white: 1, alpha: 0.38)
        let active = UIColor(EdgeTheme.sand)
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
