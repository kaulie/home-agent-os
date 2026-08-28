import UIKit

final class ReadingHubViewController: UIViewController {
    var onEnterCapture: (() -> Void)?

    private let topPanel = UIView()
    private let galleryPanel = UIView()
    private let galleryTitle = UILabel()
    private let enterButton = UIButton(type: .system)
    private let tableView = UITableView(frame: .zero, style: .plain)
    private var photos: [ReadingPhotoRecord] = []

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = LegacyTheme.background
        setupLayout()
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        reloadPhotos()
    }

    func reloadPhotos(scrollTo photoId: String? = nil, showPreview: Bool = false) {
        photos = ReadingPhotoStore.recent()
        tableView.reloadData()
        tableView.backgroundView = photos.isEmpty ? makeEmptyView() : nil
        guard let photoId = photoId, let index = photos.firstIndex(where: { $0.id == photoId }) else { return }
        let path = IndexPath(row: index, section: 0)
        tableView.scrollToRow(at: path, at: .top, animated: true)
        if showPreview {
            presentPhotoPreview(photoId: photoId)
        }
    }

    private func setupLayout() {
        topPanel.translatesAutoresizingMaskIntoConstraints = false
        galleryPanel.translatesAutoresizingMaskIntoConstraints = false
        galleryPanel.backgroundColor = LegacyTheme.card
        galleryPanel.layer.cornerRadius = 16
        galleryPanel.layer.maskedCorners = [.layerMinXMinYCorner, .layerMaxXMinYCorner]
        galleryPanel.clipsToBounds = true

        view.addSubview(topPanel)
        view.addSubview(galleryPanel)

        NSLayoutConstraint.activate([
            topPanel.topAnchor.constraint(equalTo: view.topAnchor),
            topPanel.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            topPanel.trailingAnchor.constraint(equalTo: view.trailingAnchor),

            galleryPanel.topAnchor.constraint(equalTo: topPanel.bottomAnchor, constant: 12),
            galleryPanel.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            galleryPanel.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            galleryPanel.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            galleryPanel.heightAnchor.constraint(greaterThanOrEqualToConstant: 160),
        ])

        setupEnterArea(in: topPanel)
        setupGallery(in: galleryPanel)
    }

    private func setupEnterArea(in panel: UIView) {
        let circle = UIView()
        circle.backgroundColor = LegacyTheme.accent
        circle.layer.cornerRadius = 58
        circle.translatesAutoresizingMaskIntoConstraints = false
        circle.isUserInteractionEnabled = false

        enterButton.translatesAutoresizingMaskIntoConstraints = false
        enterButton.addTarget(self, action: #selector(enterTapped), for: .touchUpInside)

        let cameraLabel = UILabel()
        cameraLabel.text = "📷"
        cameraLabel.font = UIFont.systemFont(ofSize: 40)
        cameraLabel.textAlignment = .center
        cameraLabel.translatesAutoresizingMaskIntoConstraints = false
        cameraLabel.isUserInteractionEnabled = false

        let subtitleLabel = UILabel()
        subtitleLabel.text = "开启拍照"
        subtitleLabel.font = LegacyTheme.fontTitle
        subtitleLabel.textColor = LegacyTheme.textPrimary
        subtitleLabel.textAlignment = .center
        subtitleLabel.translatesAutoresizingMaskIntoConstraints = false

        panel.addSubview(circle)
        panel.addSubview(enterButton)
        panel.addSubview(cameraLabel)
        panel.addSubview(subtitleLabel)

        NSLayoutConstraint.activate([
            circle.topAnchor.constraint(equalTo: panel.topAnchor, constant: 8),
            circle.centerXAnchor.constraint(equalTo: panel.centerXAnchor),
            circle.widthAnchor.constraint(equalToConstant: 116),
            circle.heightAnchor.constraint(equalToConstant: 116),

            enterButton.centerXAnchor.constraint(equalTo: circle.centerXAnchor),
            enterButton.centerYAnchor.constraint(equalTo: circle.centerYAnchor),
            enterButton.widthAnchor.constraint(equalToConstant: 116),
            enterButton.heightAnchor.constraint(equalToConstant: 116),

            cameraLabel.centerXAnchor.constraint(equalTo: circle.centerXAnchor),
            cameraLabel.centerYAnchor.constraint(equalTo: circle.centerYAnchor),

            subtitleLabel.topAnchor.constraint(equalTo: circle.bottomAnchor, constant: 12),
            subtitleLabel.leadingAnchor.constraint(equalTo: panel.leadingAnchor, constant: 20),
            subtitleLabel.trailingAnchor.constraint(equalTo: panel.trailingAnchor, constant: -20),
            subtitleLabel.bottomAnchor.constraint(equalTo: panel.bottomAnchor, constant: -8),
        ])
    }

    private func setupGallery(in panel: UIView) {
        galleryTitle.text = "我的照片"
        galleryTitle.font = LegacyTheme.fontHint
        galleryTitle.textColor = LegacyTheme.textPrimary
        galleryTitle.translatesAutoresizingMaskIntoConstraints = false

        tableView.translatesAutoresizingMaskIntoConstraints = false
        tableView.separatorStyle = .none
        tableView.backgroundColor = .clear
        tableView.rowHeight = 88
        tableView.dataSource = self
        tableView.delegate = self
        tableView.register(ReadingPhotoCell.self, forCellReuseIdentifier: ReadingPhotoCell.reuseId)

        panel.addSubview(galleryTitle)
        panel.addSubview(tableView)

        NSLayoutConstraint.activate([
            galleryTitle.topAnchor.constraint(equalTo: panel.topAnchor, constant: 14),
            galleryTitle.leadingAnchor.constraint(equalTo: panel.leadingAnchor, constant: 20),

            tableView.topAnchor.constraint(equalTo: galleryTitle.bottomAnchor, constant: 8),
            tableView.leadingAnchor.constraint(equalTo: panel.leadingAnchor),
            tableView.trailingAnchor.constraint(equalTo: panel.trailingAnchor),
            tableView.bottomAnchor.constraint(equalTo: panel.bottomAnchor),
        ])
    }

    private func makeEmptyView() -> UIView {
        let container = UIView()
        let label = UILabel()
        label.text = "还没有照片\n点上面「开启拍照」"
        label.numberOfLines = 0
        label.font = LegacyTheme.fontHint
        label.textColor = LegacyTheme.textMuted
        label.textAlignment = .center
        label.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: container.centerYAnchor),
        ])
        return container
    }

    private func presentPhotoPreview(photoId: String) {
        guard let image = ReadingPhotoStore.thumbnail(for: photoId) else { return }
        let preview = ReadingPhotoPreviewController(image: image)
        preview.modalPresentationStyle = .fullScreen
        present(preview, animated: true)
    }

    @objc private func enterTapped() {
        onEnterCapture?()
    }
}

extension ReadingHubViewController: UITableViewDataSource, UITableViewDelegate {
    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        photos.count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: ReadingPhotoCell.reuseId, for: indexPath) as! ReadingPhotoCell
        cell.configure(record: photos[indexPath.row])
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        presentPhotoPreview(photoId: photos[indexPath.row].id)
    }
}

private final class ReadingPhotoPreviewController: UIViewController {
    private let image: UIImage

    init(image: UIImage) {
        self.image = image
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black

        let imageView = UIImageView(image: image)
        imageView.contentMode = .scaleAspectFit
        imageView.translatesAutoresizingMaskIntoConstraints = false

        let doneButton = UIButton(type: .system)
        LegacyUI.styleKidPrimaryButton(doneButton, title: "看完了")
        doneButton.addTarget(self, action: #selector(closeTapped), for: .touchUpInside)
        doneButton.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(imageView)
        view.addSubview(doneButton)

        NSLayoutConstraint.activate([
            imageView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 12),
            imageView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            imageView.bottomAnchor.constraint(equalTo: doneButton.topAnchor, constant: -12),

            doneButton.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            doneButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            doneButton.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -16),
            doneButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 52),
        ])
    }

    @objc private func closeTapped() {
        dismiss(animated: true)
    }
}

private final class ReadingPhotoCell: UITableViewCell {
    static let reuseId = "ReadingPhotoCell"

    private let thumbView = UIImageView()
    private let titleLabel = UILabel()
    private let statusLabel = UILabel()

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear

        thumbView.contentMode = .scaleAspectFill
        thumbView.clipsToBounds = true
        thumbView.layer.cornerRadius = 10
        thumbView.backgroundColor = LegacyTheme.border
        thumbView.translatesAutoresizingMaskIntoConstraints = false

        titleLabel.font = LegacyTheme.fontHint
        titleLabel.textColor = LegacyTheme.textPrimary
        titleLabel.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        contentView.addSubview(thumbView)
        contentView.addSubview(titleLabel)
        contentView.addSubview(statusLabel)

        NSLayoutConstraint.activate([
            thumbView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16),
            thumbView.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
            thumbView.widthAnchor.constraint(equalToConstant: 72),
            thumbView.heightAnchor.constraint(equalToConstant: 72),

            titleLabel.leadingAnchor.constraint(equalTo: thumbView.trailingAnchor, constant: 12),
            titleLabel.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 22),
            titleLabel.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16),

            statusLabel.leadingAnchor.constraint(equalTo: titleLabel.leadingAnchor),
            statusLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 4),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(record: ReadingPhotoRecord) {
        thumbView.image = ReadingPhotoStore.thumbnail(for: record.id)
        let date = Date(timeIntervalSince1970: record.createdAt)
        let formatter = DateFormatter()
        formatter.dateFormat = "M月d日 HH:mm"
        titleLabel.text = "照片 · \(formatter.string(from: date))"
        switch record.uploadState {
        case .uploaded:
            statusLabel.text = "已发送 ✓"
            statusLabel.textColor = LegacyTheme.success
        case .uploading:
            statusLabel.text = "正在发送…"
            statusLabel.textColor = LegacyTheme.accent
        case .failed:
            statusLabel.text = "没发出去"
            statusLabel.textColor = LegacyTheme.danger
        case .none:
            statusLabel.text = "待发送"
            statusLabel.textColor = LegacyTheme.textMuted
        }
    }
}
