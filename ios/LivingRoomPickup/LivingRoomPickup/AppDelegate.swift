import UIKit

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        let home = HomeMicViewController()
        let nav = UINavigationController(rootViewController: home)
        nav.navigationBar.barStyle = .black
        nav.navigationBar.tintColor = .white
        nav.navigationBar.titleTextAttributes = [
            .foregroundColor: UIColor.white,
        ]
        window.rootViewController = nav
        window.makeKeyAndVisible()
        self.window = window
        // mDNS discovery (iOS 12-safe completion API): follow the Mac gateway host.
        MdnsDiscovery.resolve(MdnsDiscovery.gatewayType) { gateway in
            guard let gateway else { return }
            DispatchQueue.main.async {
                HomeMicSettings.applyDiscovered(gateway)
            }
        }
        return true
    }
}
