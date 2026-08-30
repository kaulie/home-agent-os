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
        return true
    }
}
