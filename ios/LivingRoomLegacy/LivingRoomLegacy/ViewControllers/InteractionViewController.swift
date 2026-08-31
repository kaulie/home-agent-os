import UIKit

final class InteractionViewController: UIViewController {
    private let segment = PillSegmentControl(titles: ["打字", "看书", "直播"])
    private let containerView = UIView()
    private var chatViewController: ChatViewController?
    private var chatEmbedScheduled = false
    private var readingViewController: ReadingModeViewController?
    private var liveStreamViewController: LiveStreamViewController?
    private var segmentHeight: NSLayoutConstraint?
    private var containerTopToSegment: NSLayoutConstraint?
    private var containerTopToSafeArea: NSLayoutConstraint?

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "面条之家"
        edgesForExtendedLayout = []
        view.backgroundColor = LegacyTheme.background

        segment.selectedIndex = 0
        segment.onSelectionChanged = { [weak self] index in
            self?.chatViewController?.dismissKeyboard()
            self?.showChild(at: index)
        }
        segment.translatesAutoresizingMaskIntoConstraints = false
        containerView.translatesAutoresizingMaskIntoConstraints = false
        containerView.backgroundColor = LegacyTheme.background

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

        // Mount chat immediately on iOS 12 (async embed left a blank/black content area).
        let chat = ensureChatViewController()
        embed(chat)
    }

    func refreshConnectionUI() {
        chatViewController?.refreshConnectionStatus()
    }

    private func ensureChatViewController() -> ChatViewController {
        if let chatViewController { return chatViewController }
        let vc = ChatViewController()
        chatViewController = vc
        return vc
    }

    private func scheduleChatEmbedIfNeeded() {
        guard !chatEmbedScheduled else { return }
        chatEmbedScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let chat = self.ensureChatViewController()
            guard chat.parent == nil else { return }
            self.embed(chat)
        }
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
        chatViewController?.dismissKeyboard()
        let showReading = index == 1
        let showLive = index == 2

        if showReading {
            let reading = ensureReadingViewController()
            reading.view.isHidden = false
            liveStreamViewController?.view.isHidden = true
            chatViewController?.view.isHidden = true
            reading.beginSessionIfNeeded()
            liveStreamViewController?.endSession()
        } else if showLive {
            let live = ensureLiveStreamViewController()
            readingViewController?.view.isHidden = true
            live.view.isHidden = false
            chatViewController?.view.isHidden = true
            readingViewController?.endSession()
            live.beginSessionIfNeeded()
        } else {
            scheduleChatEmbedIfNeeded()
            let chat = ensureChatViewController()
            if chat.parent == nil {
                embed(chat)
            }
            readingViewController?.view.isHidden = true
            liveStreamViewController?.view.isHidden = true
            chat.view.isHidden = false
            readingViewController?.endSession()
            liveStreamViewController?.endSession()
            setCaptureChromeHidden(false)
        }
    }

    private func ensureReadingViewController() -> ReadingModeViewController {
        if let readingViewController {
            return readingViewController
        }
        let vc = ReadingModeViewController()
        vc.onCaptureSessionActive = { [weak self] active in
            self?.setCaptureChromeHidden(active)
        }
        readingViewController = vc
        embed(vc)
        return vc
    }

    private func ensureLiveStreamViewController() -> LiveStreamViewController {
        if let liveStreamViewController {
            return liveStreamViewController
        }
        let vc = LiveStreamViewController()
        vc.onStreamActive = { [weak self] active in
            self?.setCaptureChromeHidden(active)
        }
        liveStreamViewController = vc
        embed(vc)
        return vc
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
