import SwiftUI
import UIKit

/// Seven-pane shell: 互动 · 游戏 · 电视 · 系统 · 能力 · 实体 · 节点
struct RootTabView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: EdgeTab = .chat
    /// Only mount tab roots after first visit — TabView otherwise instantiates all
    /// panes at launch (GameControllerView pulls in AVCaptureSession / Vision on main).
    @State private var loadedTabs: Set<EdgeTab> = [.chat]

    enum EdgeTab: Hashable {
        case chat
        case game
        case tv
        case system
        case runtime
        case entity
        case node
    }

    var body: some View {
        TabView(selection: $tab) {
            lazyTab(.chat) {
                ContentView()
            }

            lazyTab(.game) {
                GameControllerView()
            }

            lazyTab(.tv) {
                TVView()
            }

            lazyTab(.system) {
                SystemObserverView()
            }

            lazyTab(.runtime) {
                RuntimeCapabilitiesView()
            }

            lazyTab(.entity) {
                EntityBrowserView()
            }

            lazyTab(.node) {
                NodeInfoView()
            }
        }
        .tint(EdgeTheme.sand)
        .background(EdgeTheme.ink.ignoresSafeArea())
        .onChange(of: tab) { _, newTab in
            loadedTabs.insert(newTab)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.onForeground()
            }
        }
    }

    @ViewBuilder
    private func lazyTab<Content: View>(
        _ edge: EdgeTab,
        @ViewBuilder content: () -> Content
    ) -> some View {
        Group {
            if loadedTabs.contains(edge) {
                content()
            } else {
                EdgeTheme.ink
            }
        }
        .tabItem {
            switch edge {
            case .chat:
                Label("互动", systemImage: "bubble.left.and.bubble.right.fill")
            case .game:
                Label("游戏", systemImage: "gamecontroller.fill")
            case .tv:
                Label("电视", systemImage: "tv.fill")
            case .system:
                Label("系统", systemImage: "antenna.radiowaves.left.and.right")
            case .runtime:
                Label("能力", systemImage: "square.stack.3d.up.fill")
            case .entity:
                Label("实体", systemImage: "shippingbox")
            case .node:
                Label("节点", systemImage: "point.3.connected.trianglepath.dotted")
            }
        }
        .tag(edge)
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
