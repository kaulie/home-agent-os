import UIKit

final class MainTabBarController: UITabBarController {
    private let interactionViewController = InteractionViewController()
    private let settingsViewController = SettingsViewController()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = LegacyTheme.background
        LegacyTheme.applyTabBar(tabBar)

        interactionViewController.tabBarItem = UITabBarItem(
            title: "首页",
            image: TabIcons.home(),
            tag: 0
        )
        settingsViewController.tabBarItem = UITabBarItem(
            title: "家长",
            image: TabIcons.parent(),
            tag: 1
        )

        let interactionNav = UINavigationController(rootViewController: interactionViewController)
        let settingsNav = UINavigationController(rootViewController: settingsViewController)
        LegacyTheme.applyNavigationBar(interactionNav.navigationBar)
        LegacyTheme.applyNavigationBar(settingsNav.navigationBar)
        viewControllers = [interactionNav, settingsNav]
        delegate = self

        ConnectionManager.shared.onStatusChange = { [weak self] in
            self?.interactionViewController.refreshConnectionUI()
            self?.settingsViewController.refreshConnectionUI()
        }
    }
}

extension MainTabBarController: UITabBarControllerDelegate {
    func tabBarController(_ tabBarController: UITabBarController, didSelect viewController: UIViewController) {
        view.endEditing(true)
    }
}
