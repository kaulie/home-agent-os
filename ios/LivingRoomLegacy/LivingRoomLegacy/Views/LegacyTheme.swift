import UIKit

enum LegacyTheme {
    static let background = UIColor(red: 1.0, green: 0.973, blue: 0.941, alpha: 1.0)
    static let card = UIColor.white
    static let accent = UIColor(red: 0.91, green: 0.58, blue: 0.23, alpha: 1.0)
    static let accentSoft = UIColor(red: 1.0, green: 0.93, blue: 0.82, alpha: 1.0)
    static let textPrimary = UIColor(red: 0.20, green: 0.14, blue: 0.09, alpha: 1.0)
    static let textSecondary = UIColor(red: 0.48, green: 0.40, blue: 0.34, alpha: 1.0)
    static let textMuted = UIColor(red: 0.65, green: 0.58, blue: 0.52, alpha: 1.0)
    static let border = UIColor(red: 0.93, green: 0.87, blue: 0.79, alpha: 1.0)
    static let userBubble = accent
    static let botBubble = UIColor(red: 1.0, green: 0.96, blue: 0.90, alpha: 1.0)
    static let success = UIColor(red: 0.18, green: 0.60, blue: 0.36, alpha: 1.0)
    static let danger = UIColor(red: 0.82, green: 0.28, blue: 0.22, alpha: 1.0)
    static let segmentTrack = UIColor(red: 0.96, green: 0.91, blue: 0.84, alpha: 1.0)

    static let fontTitle = UIFont.systemFont(ofSize: 22, weight: .bold)
    static let fontBody = UIFont.systemFont(ofSize: 19)
    static let fontButton = UIFont.systemFont(ofSize: 20, weight: .bold)
    static let fontHint = UIFont.systemFont(ofSize: 17, weight: .medium)

    static func applyNavigationBar(_ navigationBar: UINavigationBar?) {
        guard let bar = navigationBar else { return }
        bar.barTintColor = background
        bar.isTranslucent = false
        bar.tintColor = accent
        bar.titleTextAttributes = [
            .foregroundColor: textPrimary,
            .font: fontTitle,
        ]
        bar.shadowImage = UIImage()
        bar.setBackgroundImage(UIImage(), for: .default)
    }

    static func applyTabBar(_ tabBar: UITabBar) {
        tabBar.barTintColor = card
        tabBar.isTranslucent = false
        tabBar.tintColor = accent
        tabBar.unselectedItemTintColor = textMuted
        let tabFont = UIFont.systemFont(ofSize: 15, weight: .semibold)
        UITabBarItem.appearance().setTitleTextAttributes([.font: tabFont], for: .normal)
        UITabBarItem.appearance().setTitleTextAttributes([.font: tabFont], for: .selected)
        if #available(iOS 13.0, *) {
            let appearance = UITabBarAppearance()
            appearance.configureWithOpaqueBackground()
            appearance.backgroundColor = card
            appearance.shadowColor = border
            tabBar.standardAppearance = appearance
        } else {
            tabBar.shadowImage = UIImage()
            tabBar.backgroundImage = UIImage()
        }
    }
}

enum LegacyUI {
    static func cardView(cornerRadius: CGFloat = 14) -> UIView {
        let view = UIView()
        view.backgroundColor = LegacyTheme.card
        view.layer.cornerRadius = cornerRadius
        view.layer.borderWidth = 1
        view.layer.borderColor = LegacyTheme.border.cgColor
        view.layer.shadowColor = UIColor.black.cgColor
        view.layer.shadowOpacity = 0.04
        view.layer.shadowOffset = CGSize(width: 0, height: 2)
        view.layer.shadowRadius = 6
        return view
    }

    static func styleKidPrimaryButton(_ button: UIButton, title: String) {
        button.setTitle(title, for: .normal)
        button.setTitleColor(.white, for: .normal)
        button.titleLabel?.font = LegacyTheme.fontButton
        button.backgroundColor = LegacyTheme.accent
        button.layer.cornerRadius = 14
        button.contentEdgeInsets = UIEdgeInsets(top: 14, left: 20, bottom: 14, right: 20)
    }

    static func stylePrimaryButton(_ button: UIButton, title: String) {
        styleKidPrimaryButton(button, title: title)
    }

    static func styleSecondaryButton(_ button: UIButton, title: String) {
        button.setTitle(title, for: .normal)
        button.setTitleColor(LegacyTheme.accent, for: .normal)
        button.titleLabel?.font = UIFont.systemFont(ofSize: 17, weight: .semibold)
        button.backgroundColor = LegacyTheme.accentSoft
        button.layer.cornerRadius = 12
        button.layer.borderWidth = 1
        button.layer.borderColor = LegacyTheme.border.cgColor
        button.contentEdgeInsets = UIEdgeInsets(top: 12, left: 16, bottom: 12, right: 16)
    }

    static func styleKidTextField(_ field: UITextField, placeholder: String) {
        field.placeholder = placeholder
        field.borderStyle = .none
        field.backgroundColor = LegacyTheme.background
        field.textColor = LegacyTheme.textPrimary
        field.font = LegacyTheme.fontBody
        field.layer.cornerRadius = 12
        field.layer.borderWidth = 1
        field.layer.borderColor = LegacyTheme.border.cgColor
        field.leftView = UIView(frame: CGRect(x: 0, y: 0, width: 14, height: 1))
        field.leftViewMode = .always
        field.clearButtonMode = .whileEditing
        field.autocapitalizationType = .none
        field.autocorrectionType = .no
    }

    static func styleTextField(_ field: UITextField, placeholder: String) {
        styleKidTextField(field, placeholder: placeholder)
        field.font = UIFont.systemFont(ofSize: 15)
    }

    static func sectionTitle(_ text: String) -> UILabel {
        let label = UILabel()
        label.text = text
        label.font = UIFont.systemFont(ofSize: 15, weight: .semibold)
        label.textColor = LegacyTheme.textSecondary
        return label
    }

    static func bodyLabel(_ lines: Int = 0) -> UILabel {
        let label = UILabel()
        label.numberOfLines = lines
        label.font = LegacyTheme.fontBody
        label.textColor = LegacyTheme.textPrimary
        return label
    }

    static func monoLabel(_ lines: Int = 0) -> UILabel {
        let label = UILabel()
        label.numberOfLines = lines
        label.font = UIFont(name: "Menlo-Regular", size: 12) ?? UIFont.systemFont(ofSize: 12)
        label.textColor = LegacyTheme.textSecondary
        return label
    }
}

enum TabIcons {
    static func home() -> UIImage? {
        drawIcon(size: CGSize(width: 28, height: 28), template: true) { _, rect in
            LegacyTheme.accent.setFill()
            let house = UIBezierPath()
            let w = rect.width
            let h = rect.height
            house.move(to: CGPoint(x: w * 0.5, y: h * 0.15))
            house.addLine(to: CGPoint(x: w * 0.85, y: h * 0.45))
            house.addLine(to: CGPoint(x: w * 0.85, y: h * 0.82))
            house.addLine(to: CGPoint(x: w * 0.15, y: h * 0.82))
            house.addLine(to: CGPoint(x: w * 0.15, y: h * 0.45))
            house.close()
            house.fill()
        }
    }

    static func parent() -> UIImage? {
        drawIcon(size: CGSize(width: 28, height: 28), template: true) { _, rect in
            LegacyTheme.accent.setFill()
            UIBezierPath(ovalIn: CGRect(x: rect.midX - 5, y: rect.minY + 3, width: 10, height: 10)).fill()
            let body = UIBezierPath(ovalIn: CGRect(x: rect.midX - 9, y: rect.midY + 2, width: 18, height: 12))
            body.fill()
        }
    }
}

enum ChatIcons {
    /// Hold-to-talk mic glyph. iOS 13+ uses SF Symbol; iOS 12 uses a filled vector fallback.
    static func microphone(diameter: CGFloat, color: UIColor) -> UIImage? {
        let pointSize = max(28, diameter * 0.88)
        if #available(iOS 13.0, *) {
            let config = UIImage.SymbolConfiguration(pointSize: pointSize, weight: .semibold)
            if let symbol = UIImage(systemName: "mic.fill", withConfiguration: config)?
                .withRenderingMode(.alwaysTemplate) {
                return symbol
            }
        }
        return legacyMicrophone(diameter: diameter)
    }

    private static func legacyMicrophone(diameter: CGFloat) -> UIImage? {
        drawIcon(size: CGSize(width: diameter, height: diameter), template: true) { _, rect in
            UIColor.black.setFill()
            let w = rect.width
            let h = rect.height
            let cx = w * 0.5

            let headW = w * 0.34
            let headH = h * 0.40
            let headY = h * 0.11
            UIBezierPath(
                roundedRect: CGRect(x: cx - headW / 2, y: headY, width: headW, height: headH),
                cornerRadius: headW / 2
            ).fill()

            let bracket = UIBezierPath()
            let bracketCenter = CGPoint(x: cx, y: headY + headH * 0.42)
            let outerR = w * 0.30
            let innerR = w * 0.20
            bracket.addArc(
                withCenter: bracketCenter,
                radius: outerR,
                startAngle: .pi * 0.22,
                endAngle: .pi * 0.78,
                clockwise: true
            )
            bracket.addArc(
                withCenter: bracketCenter,
                radius: innerR,
                startAngle: .pi * 0.78,
                endAngle: .pi * 0.22,
                clockwise: false
            )
            bracket.close()
            bracket.fill()

            let stemW = w * 0.09
            UIBezierPath(
                rect: CGRect(x: cx - stemW / 2, y: headY + headH * 0.70, width: stemW, height: h * 0.14)
            ).fill()

            let baseH = max(2.5, w * 0.09)
            UIBezierPath(
                roundedRect: CGRect(x: w * 0.27, y: h * 0.84, width: w * 0.46, height: baseH),
                cornerRadius: baseH / 2
            ).fill()
        }
    }
}

private func drawIcon(
    size: CGSize,
    template: Bool,
    draw: (CGContext, CGRect) -> Void
) -> UIImage? {
    UIGraphicsBeginImageContextWithOptions(size, false, 0)
    defer { UIGraphicsEndImageContext() }
    guard let ctx = UIGraphicsGetCurrentContext() else { return nil }
    draw(ctx, CGRect(origin: .zero, size: size))
    let image = UIGraphicsGetImageFromCurrentImageContext()
    return template ? image?.withRenderingMode(.alwaysTemplate) : image
}
