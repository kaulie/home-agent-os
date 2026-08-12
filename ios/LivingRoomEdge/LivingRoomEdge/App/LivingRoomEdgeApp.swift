import SwiftUI

@main
struct LivingRoomEdgeApp: App {
    init() {
        // Prefer early configure on main; castPhoto also configures lazily.
        Task { @MainActor in
            CastSessionController.shared.configureIfNeeded()
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(AppModel.shared)
        }
    }
}
