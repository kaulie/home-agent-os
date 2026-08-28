import UIKit

enum IntentIdCaption {
    static func text(for intentId: String) -> String {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        return id.isEmpty ? "id —" : "id \(id)"
    }

    static func attach(to label: UILabel, intentId: String) {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        label.text = text(for: intentId)
        label.font = UIFont(name: "Menlo-Regular", size: 11) ?? UIFont.systemFont(ofSize: 11)
        label.textColor = LegacyTheme.textMuted
        label.isHidden = false
        label.isUserInteractionEnabled = !id.isEmpty
        label.accessibilityLabel = "intent_id"
    }

    static func copy(_ intentId: String, presenter: UIViewController) {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        UIPasteboard.general.string = id
        let alert = UIAlertController(title: nil, message: "已复制 id \(id)", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        presenter.present(alert, animated: true)
    }
}
