import SwiftUI

@main
struct HomeAgentRelayApp: App {
    @ObservedObject private var server = RelayServer.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(server)
                .onAppear {
                    server.start()
                }
        }
    }
}
