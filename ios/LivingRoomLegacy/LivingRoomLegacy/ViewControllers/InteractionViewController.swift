import UIKit

final class InteractionViewController: UIViewController {
    private let segment = PillSegmentControl(titles: ["打字", "看书"])
    private let containerView = UIView()
    private let chatViewController = ChatViewController()
    private let readingViewController = ReadingModeViewController()
    private var segmentHeight: NSLayoutConstraint?
    private var containerTopToSegment: NSLayoutConstraint?
    private var containerTopToSafeArea: NSLayoutConstraint?

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "面条之家"
        view.backgroundColor = LegacyTheme.background

        segment.selectedIndex = 0
        segment.onSelectionChanged = { [weak self] index in
            self?.chatViewController.dismissKeyboard()
            self?.showChild(at: index)
        }
        segment.translatesAutoresizingMaskIntoConstraints = false
        containerView.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(segment)
        view.addSubview(containerView)

        segmentHeight = segment.heightAnchor.constraint(equalToConstant: 52)
        containerTopToSegment = containerView.topAnchor.constraint(equalTo: segment.bottomAnchor, constant: 12)
        containerTopToSafeArea = containerView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8)

        NSLayoutConstraint.activate([
            segment.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            segment.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            segment.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            segmentHeight!,

            containerTopToSegment!,
            containerView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            containerView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            containerView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        readingViewController.onCaptureSessionActive = { [weak self] active in
            self?.setCaptureChromeHidden(active)
        }

        embed(chatViewController)
        embed(readingViewController)
        readingViewController.view.isHidden = true
        showChild(at: 0)
    }

    func refreshConnectionUI() {
        chatViewController.refreshConnectionStatus()
    }

    private func setCaptureChromeHidden(_ hidden: Bool) {
        segment.isHidden = hidden
        segmentHeight?.constant = hidden ? 0 : 52
        containerTopToSegment?.isActive = !hidden
        containerTopToSafeArea?.isActive = hidden
        navigationController?.setNavigationBarHidden(hidden, animated: true)
        tabBarController?.tabBar.isHidden = hidden
        view.layoutIfNeeded()
    }

    private func showChild(at index: Int) {
        chatViewController.dismissKeyboard()
        let showReading = index == 1
        readingViewController.view.isHidden = !showReading
        chatViewController.view.isHidden = showReading
        if showReading {
            readingViewController.beginSessionIfNeeded()
        } else {
            readingViewController.endSession()
            setCaptureChromeHidden(false)
        }
    }

    private func embed(_ child: UIViewController) {
        addChild(child)
        child.view.translatesAutoresizingMaskIntoConstraints = false
        containerView.addSubview(child.view)
        NSLayoutConstraint.activate([
            child.view.topAnchor.constraint(equalTo: containerView.topAnchor),
            child.view.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            child.view.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
            child.view.bottomAnchor.constraint(equalTo: containerView.bottomAnchor),
        ])
        child.didMove(toParent: self)
    }
}
