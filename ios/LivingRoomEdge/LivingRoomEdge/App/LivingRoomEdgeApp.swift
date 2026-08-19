import SwiftUI

@main
struct LivingRoomEdgeApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(AppModel.shared)
        }
    }
}
