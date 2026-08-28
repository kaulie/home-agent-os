import UIKit

private enum ReadingScreen {
    case hub
    case capture
}

final class ReadingModeViewController: UIViewController {
    var onCaptureSessionActive: ((Bool) -> Void)?

    private let hubViewController = ReadingHubViewController()
    private let captureViewController = ReadingCaptureViewController()
    private let containerView = UIView()
    private var screen: ReadingScreen = .hub

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = LegacyTheme.background
        containerView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(containerView)
        NSLayoutConstraint.activate([
            containerView.topAnchor.constraint(equalTo: view.topAnchor),
            containerView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            containerView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            containerView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        hubViewController.onEnterCapture = { [weak self] in
            self?.showCapture()
        }
        captureViewController.onExit = { [weak self] in
            self?.showHub()
        }
        captureViewController.onPhotoCaptured = { [weak self] photoId in
            self?.showHub(highlightPhotoId: photoId, showPreview: true)
        }
        captureViewController.onPhotoUploadChanged = { [weak self] in
            self?.hubViewController.reloadPhotos()
        }

        embed(hubViewController)
        embed(captureViewController)
        captureViewController.view.isHidden = true
    }

    func beginSessionIfNeeded() {
        if screen == .capture {
            captureViewController.startSession()
        }
    }

    func endSession() {
        if screen == .capture {
            showHub()
        }
    }

    private func showHub(highlightPhotoId: String? = nil, showPreview: Bool = false) {
        screen = .hub
        captureViewController.stopSession()
        captureViewController.view.isHidden = true
        hubViewController.view.isHidden = false
        hubViewController.reloadPhotos(scrollTo: highlightPhotoId, showPreview: showPreview)
        onCaptureSessionActive?(false)
    }

    private func showCapture() {
        screen = .capture
        hubViewController.view.isHidden = true
        captureViewController.view.isHidden = false
        captureViewController.startSession()
        onCaptureSessionActive?(true)
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
