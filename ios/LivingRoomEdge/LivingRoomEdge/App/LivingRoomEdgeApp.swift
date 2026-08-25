import SwiftUI
import UIKit

@main
struct LivingRoomEdgeApp: App {
    init() {
        // Configure before first TabView layout — mutating UITabBar.appearance()
        // from TabView.onAppear can hitch / re-enter layout on some devices.
        RootTabView.configureTabBarAppearanceOnce()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environmentObject(AppModel.shared)
                .preferredColorScheme(.dark)
        }
    }
}
