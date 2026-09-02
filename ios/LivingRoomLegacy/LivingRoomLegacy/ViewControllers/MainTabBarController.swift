import UIKit

final class MainTabBarController: UITabBarController, UITabBarControllerDelegate {
    private lazy var interactionViewController = InteractionViewController()
    private lazy var settingsViewController = SettingsViewController()
    private lazy var interactionNav: UINavigationController = {
        let nav = UINavigationController(rootViewController: interactionViewController)
        LegacyTheme.applyNavigationBar(nav.navigationBar)
        nav.tabBarItem = UITabBarItem(title: "首页", image: TabIcons.home(), tag: 0)
        return nav
    }()
    private lazy var settingsNav: UINavigationController = {
        let nav = UINavigationController(rootViewController: settingsViewController)
        LegacyTheme.applyNavigationBar(nav.navigationBar)
        nav.tabBarItem = UITabBarItem(title: "家长", image: TabIcons.parent(), tag: 1)
        return nav
    }()
    private let settingsPlaceholder = UIViewController()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = LegacyTheme.background
        LegacyTheme.applyTabBar(tabBar)
        delegate = self

        settingsPlaceholder.view.backgroundColor = LegacyTheme.background
        settingsPlaceholder.tabBarItem = UITabBarItem(
            title: "家长",
            image: TabIcons.parent(),
            tag: 1
        )

        viewControllers = [interactionNav, settingsPlaceholder]

        ConnectionManager.shared.onStatusChange = { [weak self] in
            self?.interactionViewController.refreshConnectionUI()
            if self?.viewControllers?.contains(where: { $0 === self?.settingsNav }) == true {
                self?.settingsViewController.refreshConnectionUI()
            }
        }
    }

    func tabBarController(_ tabBarController: UITabBarController, shouldSelect viewController: UIViewController) -> Bool {
        view.endEditing(true)
        guard viewController === settingsPlaceholder else { return true }
        viewControllers = [interactionNav, settingsNav]
        selectedViewController = settingsNav
        return false
    }
}
