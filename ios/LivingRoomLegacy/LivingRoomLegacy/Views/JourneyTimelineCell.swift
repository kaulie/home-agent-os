import UIKit

final class JourneyTimelineCell: UITableViewCell {
    static let reuseId = "JourneyTimelineCell"

    private let cardView = UIView()
    private let bannerLabel = UILabel()
    private let intentIdLabel = UILabel()
    private let stepsRow = UIStackView()
    private var storedIntentId = ""

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear
        contentView.backgroundColor = .clear

        cardView.backgroundColor = LegacyTheme.accentSoft
        cardView.layer.cornerRadius = 12
        cardView.layer.borderWidth = 1
        cardView.layer.borderColor = LegacyTheme.border.cgColor
        cardView.translatesAutoresizingMaskIntoConstraints = false

        bannerLabel.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
        bannerLabel.textColor = LegacyTheme.textPrimary
        bannerLabel.numberOfLines = 2
        bannerLabel.translatesAutoresizingMaskIntoConstraints = false

        intentIdLabel.translatesAutoresizingMaskIntoConstraints = false
        intentIdLabel.textAlignment = .left
        let tap = UITapGestureRecognizer(target: self, action: #selector(copyIntentIdTapped))
        intentIdLabel.addGestureRecognizer(tap)

        stepsRow.axis = .horizontal
        stepsRow.distribution = .fillEqually
        stepsRow.alignment = .top
        stepsRow.spacing = 4
        stepsRow.translatesAutoresizingMaskIntoConstraints = false

        cardView.addSubview(bannerLabel)
        cardView.addSubview(intentIdLabel)
        cardView.addSubview(stepsRow)
        contentView.addSubview(cardView)

        NSLayoutConstraint.activate([
            cardView.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 2),
            cardView.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -6),
            cardView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16),
            cardView.trailingAnchor.constraint(lessThanOrEqualTo: contentView.trailingAnchor, constant: -48),
            cardView.widthAnchor.constraint(greaterThanOrEqualToConstant: 240),
            cardView.widthAnchor.constraint(lessThanOrEqualTo: contentView.widthAnchor, multiplier: 0.88),

            bannerLabel.topAnchor.constraint(equalTo: cardView.topAnchor, constant: 10),
            bannerLabel.leadingAnchor.constraint(equalTo: cardView.leadingAnchor, constant: 12),
            bannerLabel.trailingAnchor.constraint(equalTo: cardView.trailingAnchor, constant: -12),

            intentIdLabel.topAnchor.constraint(equalTo: bannerLabel.bottomAnchor, constant: 4),
            intentIdLabel.leadingAnchor.constraint(equalTo: cardView.leadingAnchor, constant: 12),
            intentIdLabel.trailingAnchor.constraint(equalTo: cardView.trailingAnchor, constant: -12),

            stepsRow.topAnchor.constraint(equalTo: intentIdLabel.bottomAnchor, constant: 8),
            stepsRow.leadingAnchor.constraint(equalTo: cardView.leadingAnchor, constant: 8),
            stepsRow.trailingAnchor.constraint(equalTo: cardView.trailingAnchor, constant: -8),
            stepsRow.bottomAnchor.constraint(equalTo: cardView.bottomAnchor, constant: -10),
            stepsRow.heightAnchor.constraint(greaterThanOrEqualToConstant: 44),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(timeline: IntentTimeline) {
        bannerLabel.text = timeline.simpleBanner
        storedIntentId = timeline.intentId
        IntentIdCaption.attach(to: intentIdLabel, intentId: timeline.intentId)
        stepsRow.arrangedSubviews.forEach { $0.removeFromSuperview() }
        for step in timeline.simpleSteps {
            stepsRow.addArrangedSubview(makeStepColumn(step: step))
        }
    }

    @objc private func copyIntentIdTapped() {
        guard let vc = nearestViewController() else { return }
        IntentIdCaption.copy(storedIntentId, presenter: vc)
    }

    private func makeStepColumn(step: SimpleProgressStep) -> UIView {
        let column = UIStackView()
        column.axis = .vertical
        column.alignment = .center
        column.spacing = 6

        let dot = UIView()
        dot.translatesAutoresizingMaskIntoConstraints = false
        dot.layer.cornerRadius = 7
        NSLayoutConstraint.activate([
            dot.widthAnchor.constraint(equalToConstant: 14),
            dot.heightAnchor.constraint(equalToConstant: 14),
        ])

        switch step.state {
        case .done:
            dot.backgroundColor = LegacyTheme.success
        case .active:
            dot.backgroundColor = LegacyTheme.accent
            dot.layer.borderWidth = 2
            dot.layer.borderColor = LegacyTheme.accent.withAlphaComponent(0.35).cgColor
        case .failed:
            dot.backgroundColor = LegacyTheme.danger
        case .pending:
            dot.backgroundColor = LegacyTheme.border
        }

        let label = UILabel()
        label.text = step.label
        label.font = UIFont.systemFont(ofSize: 13, weight: step.state == .active ? .semibold : .regular)
        label.textAlignment = .center
        label.numberOfLines = 2
        switch step.state {
        case .done:
            label.textColor = LegacyTheme.textSecondary
        case .active:
            label.textColor = LegacyTheme.textPrimary
        case .failed:
            label.textColor = LegacyTheme.danger
        case .pending:
            label.textColor = LegacyTheme.textMuted
        }

        column.addArrangedSubview(dot)
        column.addArrangedSubview(label)
        return column
    }
}

private extension UIView {
    func nearestViewController() -> UIViewController? {
        var responder: UIResponder? = self
        while let current = responder {
            if let vc = current as? UIViewController { return vc }
            responder = current.next
        }
        return nil
    }
}
