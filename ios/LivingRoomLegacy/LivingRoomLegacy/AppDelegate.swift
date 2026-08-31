import UIKit

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = MainTabBarController()
        window.makeKeyAndVisible()
        self.window = window

        ConnectionManager.shared.startAutoConnect()
        // mDNS discovery (iOS 12-safe completion API): keep LAN slots in sync with
        // the discoverable Brain / Gateway instead of a fixed LAN IP.
        MdnsDiscovery.resolve(MdnsDiscovery.brainType) { brain in
            guard let brain else { return }
            DispatchQueue.main.async {
                ParticipantStore.homeBrainIntentURL = brain.baseURL + "/api/v1/intent"
            }
        }
        MdnsDiscovery.resolve(MdnsDiscovery.gatewayType) { gateway in
            guard let gateway else { return }
            DispatchQueue.main.async {
                ParticipantStore.macIngestURL = gateway.baseURL
            }
        }
        return true
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        ConnectionManager.shared.applicationDidBecomeActive()
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        ConnectionManager.shared.applicationDidEnterBackground()
    }
}
