import SwiftUI

@main
struct HomeAgentDevApp: App {
    @StateObject private var store = DevStore()

    init() {
        RootTabView.configureTabBarAppearanceOnce()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(store)
                .preferredColorScheme(.dark)
                .task { await DevBrainEndpoint.autoDiscoverLanBrain() }
        }
    }
}
