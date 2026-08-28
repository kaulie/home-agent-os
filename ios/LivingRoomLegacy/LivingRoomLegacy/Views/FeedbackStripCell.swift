import UIKit

final class FeedbackStripCell: UITableViewCell {
    static let reuseId = "FeedbackStripCell"

    var onTap: (() -> Void)?

    private let button = UIButton(type: .system)
    private let statusLabel = UILabel()
    private let spinner = UIActivityIndicatorView(style: .gray)

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear
        contentView.backgroundColor = .clear

        button.translatesAutoresizingMaskIntoConstraints = false
        LegacyUI.styleSecondaryButton(button, title: "一键反馈")
        button.addTarget(self, action: #selector(tapped), for: .touchUpInside)

        statusLabel.font = UIFont.systemFont(ofSize: 13)
        statusLabel.textColor = LegacyTheme.textSecondary
        statusLabel.numberOfLines = 2
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        spinner.hidesWhenStopped = true
        spinner.translatesAutoresizingMaskIntoConstraints = false

        contentView.addSubview(button)
        contentView.addSubview(statusLabel)
        contentView.addSubview(spinner)

        NSLayoutConstraint.activate([
            button.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 2),
            button.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16),
            button.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -6),

            spinner.centerYAnchor.constraint(equalTo: button.centerYAnchor),
            spinner.trailingAnchor.constraint(equalTo: button.leadingAnchor, constant: -8),

            statusLabel.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16),
            statusLabel.leadingAnchor.constraint(greaterThanOrEqualTo: contentView.leadingAnchor, constant: 16),
            statusLabel.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(state: FeedbackStripState) {
        switch state {
        case .ready:
            button.isHidden = false
            button.isEnabled = true
            button.setTitle("一键反馈", for: .normal)
            statusLabel.text = ""
            statusLabel.textColor = LegacyTheme.textSecondary
            spinner.stopAnimating()
        case .busy:
            button.isHidden = false
            button.isEnabled = false
            button.setTitle("提交中…", for: .normal)
            statusLabel.text = ""
            spinner.startAnimating()
        case .submitted(let message):
            button.isHidden = true
            statusLabel.text = message
            statusLabel.textAlignment = .right
            statusLabel.textColor = LegacyTheme.success
            spinner.stopAnimating()
        case .error(let message):
            button.isHidden = false
            button.isEnabled = true
            button.setTitle("再试一次", for: .normal)
            statusLabel.text = message
            statusLabel.textAlignment = .right
            statusLabel.textColor = LegacyTheme.danger
            spinner.stopAnimating()
        }
    }

    @objc private func tapped() {
        onTap?()
    }
}

enum FeedbackStripState: Equatable {
    case ready
    case busy
    case submitted(String)
    case error(String)
}
