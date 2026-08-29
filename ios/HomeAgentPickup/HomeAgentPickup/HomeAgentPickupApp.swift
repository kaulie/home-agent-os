import SwiftUI

@main
struct HomeAgentPickupApp: App {
    @StateObject private var model = PickupViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onAppear {
                    UIApplication.shared.isIdleTimerDisabled = true
                    Task { await model.bootstrap() }
                }
        }
    }
}
