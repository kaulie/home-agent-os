import UIKit

final class PillSegmentControl: UIView {
    var selectedIndex: Int = 0 {
        didSet { updateSelection(animated: true) }
    }
    var onSelectionChanged: ((Int) -> Void)?

    private let trackView = UIView()
    private let highlightView = UIView()
    private var buttons: [UIButton] = []
    private var highlightLeading: NSLayoutConstraint?
    private var highlightWidth: NSLayoutConstraint?

    init(titles: [String]) {
        super.init(frame: .zero)
        setContentHuggingPriority(.defaultLow, for: .horizontal)
        setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        trackView.backgroundColor = LegacyTheme.segmentTrack
        trackView.layer.cornerRadius = 16
        trackView.translatesAutoresizingMaskIntoConstraints = false

        highlightView.backgroundColor = LegacyTheme.card
        highlightView.layer.cornerRadius = 13
        highlightView.layer.shadowColor = UIColor.black.cgColor
        highlightView.layer.shadowOpacity = 0.08
        highlightView.layer.shadowOffset = CGSize(width: 0, height: 1)
        highlightView.layer.shadowRadius = 3
        highlightView.translatesAutoresizingMaskIntoConstraints = false

        addSubview(trackView)
        trackView.addSubview(highlightView)

        var previous: UIButton?
        for (index, title) in titles.enumerated() {
            let button = UIButton(type: .system)
            button.setTitle(title, for: .normal)
            button.titleLabel?.font = LegacyTheme.fontHint
            button.tag = index
            button.addTarget(self, action: #selector(tapped(_:)), for: .touchUpInside)
            button.translatesAutoresizingMaskIntoConstraints = false
            trackView.addSubview(button)
            buttons.append(button)

            NSLayoutConstraint.activate([
                button.topAnchor.constraint(equalTo: trackView.topAnchor, constant: 5),
                button.bottomAnchor.constraint(equalTo: trackView.bottomAnchor, constant: -5),
            ])
            if let prev = previous {
                button.leadingAnchor.constraint(equalTo: prev.trailingAnchor).isActive = true
                button.widthAnchor.constraint(equalTo: prev.widthAnchor).isActive = true
            } else {
                button.leadingAnchor.constraint(equalTo: trackView.leadingAnchor, constant: 5).isActive = true
            }
            if index == titles.count - 1 {
                button.trailingAnchor.constraint(equalTo: trackView.trailingAnchor, constant: -5).isActive = true
            }
            previous = button
        }

        let trackHeight = trackView.heightAnchor.constraint(equalToConstant: 52)
        trackHeight.priority = .required

        highlightWidth = highlightView.widthAnchor.constraint(
            equalTo: trackView.widthAnchor,
            multiplier: 1.0 / CGFloat(max(titles.count, 1)),
            constant: -10
        )
        highlightWidth?.priority = UILayoutPriority(999)

        NSLayoutConstraint.activate([
            trackView.topAnchor.constraint(equalTo: topAnchor),
            trackView.leadingAnchor.constraint(equalTo: leadingAnchor),
            trackView.trailingAnchor.constraint(equalTo: trailingAnchor),
            trackView.bottomAnchor.constraint(equalTo: bottomAnchor),
            trackHeight,

            highlightView.topAnchor.constraint(equalTo: trackView.topAnchor, constant: 5),
            highlightView.bottomAnchor.constraint(equalTo: trackView.bottomAnchor, constant: -5),
            highlightWidth!,
        ])
        if let first = buttons.first {
            highlightLeading = highlightView.leadingAnchor.constraint(equalTo: first.leadingAnchor)
            highlightLeading?.isActive = true
        }
        updateSelection(animated: false)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var intrinsicContentSize: CGSize {
        CGSize(width: UIView.noIntrinsicMetric, height: 52)
    }

    @objc private func tapped(_ sender: UIButton) {
        guard selectedIndex != sender.tag else { return }
        selectedIndex = sender.tag
        onSelectionChanged?(selectedIndex)
    }

    private func updateSelection(animated: Bool) {
        for button in buttons {
            let selected = button.tag == selectedIndex
            button.setTitleColor(selected ? LegacyTheme.textPrimary : LegacyTheme.textMuted, for: .normal)
        }
        repositionHighlight()
        guard animated, bounds.width > 1 else { return }
        UIView.animate(withDuration: 0.22, delay: 0, options: .curveEaseOut) {
            self.layoutIfNeeded()
        }
    }

    private func repositionHighlight() {
        guard bounds.width > 1, let target = buttons.first(where: { $0.tag == selectedIndex }) else { return }
        highlightLeading?.isActive = false
        highlightLeading = highlightView.leadingAnchor.constraint(equalTo: target.leadingAnchor)
        highlightLeading?.isActive = true
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        repositionHighlight()
    }
}
