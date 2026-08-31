import UIKit

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    private static var skippedFirstBecomeActive = false

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        ParticipantStore.migrateLegacyEndpointsIfNeeded()
        ParticipantStore.clearStaleLanEndpointsIfNeeded()

        DiscoveryDebugLog.shared.log("app launch iOS=\(UIDevice.current.systemVersion)", category: "launch")
        MdnsDiscovery.logLaunchNetworkContext()

        let window = UIWindow(frame: UIScreen.main.bounds)
        window.backgroundColor = LegacyTheme.background
        window.rootViewController = MainTabBarController()
        window.makeKeyAndVisible()
        self.window = window
        ConnectionManager.shared.startAutoConnect()
        return true
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        if !Self.skippedFirstBecomeActive {
            Self.skippedFirstBecomeActive = true
            return
        }
        ConnectionManager.shared.applicationDidBecomeActive()
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        ConnectionManager.shared.applicationDidEnterBackground()
    }
}
