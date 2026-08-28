import UIKit

final class ChatMessageCell: UITableViewCell {
    static let reuseId = "ChatMessageCell"

    private let bubbleView = UIView()
    private let messageLabel = UILabel()
    private let intentIdLabel = UILabel()
    private var bubbleLeading: NSLayoutConstraint?
    private var bubbleTrailing: NSLayoutConstraint?
    private var intentIdTrailing: NSLayoutConstraint?
    private var bubbleBottomToContent: NSLayoutConstraint?
    private var intentIdBottomToContent: NSLayoutConstraint?
    private var storedIntentId = ""

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear
        contentView.backgroundColor = .clear

        bubbleView.layer.cornerRadius = 18
        bubbleView.translatesAutoresizingMaskIntoConstraints = false

        messageLabel.numberOfLines = 0
        messageLabel.font = LegacyTheme.fontBody
        messageLabel.translatesAutoresizingMaskIntoConstraints = false

        intentIdLabel.translatesAutoresizingMaskIntoConstraints = false
        intentIdLabel.textAlignment = .right
        let tap = UITapGestureRecognizer(target: self, action: #selector(copyIntentIdTapped))
        intentIdLabel.addGestureRecognizer(tap)

        bubbleView.addSubview(messageLabel)
        contentView.addSubview(bubbleView)
        contentView.addSubview(intentIdLabel)

        bubbleLeading = bubbleView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16)
        bubbleTrailing = bubbleView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16)
        intentIdTrailing = intentIdLabel.trailingAnchor.constraint(equalTo: bubbleView.trailingAnchor)
        bubbleBottomToContent = bubbleView.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -6)
        intentIdBottomToContent = intentIdLabel.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -6)

        NSLayoutConstraint.activate([
            bubbleView.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 6),
            bubbleView.widthAnchor.constraint(lessThanOrEqualTo: contentView.widthAnchor, multiplier: 0.82),

            messageLabel.topAnchor.constraint(equalTo: bubbleView.topAnchor, constant: 12),
            messageLabel.bottomAnchor.constraint(equalTo: bubbleView.bottomAnchor, constant: -12),
            messageLabel.leadingAnchor.constraint(equalTo: bubbleView.leadingAnchor, constant: 14),
            messageLabel.trailingAnchor.constraint(equalTo: bubbleView.trailingAnchor, constant: -14),

            intentIdLabel.topAnchor.constraint(equalTo: bubbleView.bottomAnchor, constant: 4),
            intentIdLabel.leadingAnchor.constraint(greaterThanOrEqualTo: contentView.leadingAnchor, constant: 16),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(text: String, isUser: Bool, isWaiting: Bool, intentId: String = "") {
        messageLabel.text = text
        storedIntentId = intentId

        if isUser {
            bubbleView.backgroundColor = LegacyTheme.userBubble
            bubbleView.layer.borderWidth = 0
            messageLabel.textColor = .white
            bubbleLeading?.isActive = false
            bubbleTrailing?.isActive = true
            intentIdTrailing?.isActive = true
            IntentIdCaption.attach(to: intentIdLabel, intentId: intentId)
            bubbleBottomToContent?.isActive = false
            intentIdBottomToContent?.isActive = true
        } else {
            bubbleView.backgroundColor = LegacyTheme.botBubble
            bubbleView.layer.borderWidth = 1
            bubbleView.layer.borderColor = LegacyTheme.border.cgColor
            messageLabel.textColor = isWaiting ? LegacyTheme.textMuted : LegacyTheme.textPrimary
            bubbleTrailing?.isActive = false
            bubbleLeading?.isActive = true
            intentIdLabel.isHidden = true
            intentIdLabel.isUserInteractionEnabled = false
            bubbleBottomToContent?.isActive = true
            intentIdBottomToContent?.isActive = false
        }
    }

    @objc private func copyIntentIdTapped() {
        guard let vc = nearestViewController() else { return }
        IntentIdCaption.copy(storedIntentId, presenter: vc)
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
