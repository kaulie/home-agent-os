import SwiftUI
import UIKit

struct RootTabView: View {
    @EnvironmentObject private var store: DevStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: DevTab = .issues

    enum DevTab: Hashable {
        case issues
        case tasks
        case chat
        case fleet
        case deploy
        case docs
        case stats
        case connection
    }

    var body: some View {
        TabView(selection: $tab) {
            IssueListView()
                .tabItem {
                    Label("Issue", systemImage: "ladybug")
                }
                .tag(DevTab.issues)

            DevTaskConsoleView()
                .tabItem {
                    Label("Dev Task", systemImage: "terminal")
                }
                .tag(DevTab.tasks)

            ChatConsoleView()
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right")
                }
                .tag(DevTab.chat)

            FleetConsoleView()
                .tabItem {
                    Label("Fleet", systemImage: "person.3")
                }
                .tag(DevTab.fleet)

            DeployConsoleView()
                .tabItem {
                    Label("Deploy", systemImage: "arrow.up.circle")
                }
                .tag(DevTab.deploy)

            DocsConsoleView()
                .tabItem {
                    Label("文档", systemImage: "book.pages")
                }
                .tag(DevTab.docs)

            DevStatsView()
                .tabItem {
                    Label("统计", systemImage: "chart.bar")
                }
                .tag(DevTab.stats)

            DevConnectionView()
                .tabItem {
                    Label("连接", systemImage: "link")
                }
                .tag(DevTab.connection)
        }
        .tint(DevTheme.sand)
        .background(DevTheme.ink.ignoresSafeArea())
        .onChange(of: scenePhase) { phase in
            syncPolling(phase: phase, tab: tab)
        }
        .onChange(of: tab) { next in
            syncPolling(phase: scenePhase, tab: next)
        }
        .onAppear {
            syncPolling(phase: scenePhase, tab: tab)
        }
        .onDisappear {
            store.stopIssuesPolling()
            store.stopDevTaskPolling()
            store.stopChatPolling()
            store.stopFleetPolling()
            store.stopDeployPolling()
            store.stopStatsPolling()
        }
    }

    private func syncPolling(phase: ScenePhase, tab: DevTab) {
        store.stopIssuesPolling()
        store.stopDevTaskPolling()
        store.stopChatPolling()
        store.stopFleetPolling()
        store.stopDeployPolling()
        store.stopStatsPolling()
        guard phase == .active else { return }
        switch tab {
        case .issues:
            store.startIssuesPolling()
        case .tasks:
            store.startDevTaskPolling()
        case .chat:
            store.startChatPolling()
        case .fleet:
            store.startFleetPolling()
        case .deploy:
            store.startDeployPolling()
        case .docs:
            break
        case .stats:
            store.startStatsPolling()
        case .connection:
            break
        }
    }

    static func configureTabBarAppearanceOnce() {
        struct Token { static var done = false }
        guard !Token.done else { return }
        Token.done = true
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(DevTheme.ink)
        let item = UITabBarItemAppearance()
        let muted = UIColor(white: 1, alpha: 0.38)
        let active = UIColor(DevTheme.sand)
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
