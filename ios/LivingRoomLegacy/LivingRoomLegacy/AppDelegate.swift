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
        return true
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        ConnectionManager.shared.applicationDidBecomeActive()
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        ConnectionManager.shared.applicationDidEnterBackground()
    }
}
