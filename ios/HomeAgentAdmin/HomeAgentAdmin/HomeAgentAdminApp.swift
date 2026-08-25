import SwiftUI

@main
struct HomeAgentAdminApp: App {
    @StateObject private var store = AdminStore()

    init() {
        RootTabView.configureTabBarAppearanceOnce()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(store)
                .preferredColorScheme(.dark)
        }
    }
}
