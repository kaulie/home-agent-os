import UIKit

enum PickupTheme {
    static let canvas = UIColor(red: 0.07, green: 0.08, blue: 0.11, alpha: 1)
    static let canvasWarm = UIColor(red: 0.11, green: 0.09, blue: 0.08, alpha: 1)
    static let success = UIColor(red: 0.32, green: 0.78, blue: 0.48, alpha: 1)
    static let accent = UIColor(red: 0.96, green: 0.62, blue: 0.28, alpha: 1)
    static let accentSoft = UIColor(red: 0.96, green: 0.62, blue: 0.28, alpha: 0.16)
    static let micIdle = UIColor(white: 0.26, alpha: 1)
    static let micLive = UIColor(red: 0.88, green: 0.18, blue: 0.22, alpha: 1)
    static let textPrimary = UIColor(white: 0.94, alpha: 1)
    static let textSecondary = UIColor(white: 0.62, alpha: 1)
    static let textMuted = UIColor(white: 0.45, alpha: 1)
    static let fontHint = UIFont.systemFont(ofSize: 16, weight: .medium)
    static let fontBody = UIFont.systemFont(ofSize: 16, weight: .regular)
    static let fontDisplay = UIFont.systemFont(ofSize: 28, weight: .bold)
    static let fontTipTitle = UIFont.systemFont(ofSize: 17, weight: .semibold)
    static let fontTipBody = UIFont.systemFont(ofSize: 14, weight: .regular)
}

enum PickupCopy {
    static let wakePhrase = "面条 面条"
    static let wakeAck = "我在呢"

    static func idleHeadline() -> String { "准备好了" }

    static func listeningHeadline(connected: Bool) -> String {
        connected ? "正在听" : "准备听"
    }

    static func tipTitle(listening: Bool) -> String {
        listening ? "可以这样叫我" : "先认识一下"
    }

    static func tipAttributed(listening: Bool) -> NSAttributedString {
        let phrase = wakePhrase
        let full: String
        if listening {
            full = "先说「\(phrase)」唤醒我噢\n听见手机说「\(wakeAck)」后再说指令"
        } else {
            full = "点开话筒后，先说「\(phrase)」\n应答会从本机喇叭出来噢"
        }
        let attr = NSMutableAttributedString(
            string: full,
            attributes: [
                .font: PickupTheme.fontTipBody,
                .foregroundColor: PickupTheme.textSecondary,
            ]
        )
        let ns = full as NSString
        let range = ns.range(of: "「\(phrase)」")
        if range.location != NSNotFound {
            attr.addAttributes(
                [
                    .font: UIFont.systemFont(ofSize: 15, weight: .bold),
                    .foregroundColor: PickupTheme.accent,
                ],
                range: range
            )
        }
        let ackRange = ns.range(of: "「\(wakeAck)」")
        if ackRange.location != NSNotFound {
            attr.addAttributes(
                [
                    .font: UIFont.systemFont(ofSize: 14, weight: .semibold),
                    .foregroundColor: PickupTheme.textPrimary,
                ],
                range: ackRange
            )
        }
        return attr
    }

    static func footerHint(listening: Bool, connected: Bool) -> String {
        if !listening {
            return "点一下大按钮，开始拾音"
        }
        if !connected {
            return "正在连接客厅…稍等一下"
        }
        return "对着话筒说，看下面电平会不会跳"
    }

    static let stepsIdle = ["① 开麦", "② 面条面条", "③ 说指令"]
    static let stepsListening = ["① 已开麦", "② 先唤醒", "③ 再指令"]
}

enum PickupIcons {
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
        UIGraphicsBeginImageContextWithOptions(CGSize(width: diameter, height: diameter), false, 0)
        defer { UIGraphicsEndImageContext() }
        UIColor.black.setFill()
        let w = diameter
        let h = diameter
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

        return UIGraphicsGetImageFromCurrentImageContext()?.withRenderingMode(.alwaysTemplate)
    }
}
