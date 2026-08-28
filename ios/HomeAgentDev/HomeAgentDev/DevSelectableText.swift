import SwiftUI
import UIKit

/// Read-only text with reliable partial selection / copy (long-press on iPhone, right-click on iPad pointer).
struct DevSelectableText: View {
    let text: String
    var font: Font = .system(size: 14, design: .rounded)
    var weight: Font.Weight = .medium
    var mono: Bool = false
    var color: Color = DevTheme.mist
    var prominent: Bool = false

    var body: some View {
        DevSelectableTextRepresentable(
            text: text,
            uiFont: uiFont,
            color: UIColor(color)
        )
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var uiFont: UIFont {
        let size: CGFloat = prominent ? 16 : (mono ? 13 : 14)
        if mono {
            return .monospacedSystemFont(ofSize: size, weight: prominent ? .semibold : .medium)
        }
        let base = UIFont.systemFont(ofSize: size, weight: prominent ? .semibold : weight.uiWeight)
        if let rounded = base.fontDescriptor.withDesign(.rounded) {
            return UIFont(descriptor: rounded, size: size)
        }
        return base
    }
}

private struct DevSelectableTextRepresentable: UIViewRepresentable {
    let text: String
    let uiFont: UIFont
    let color: UIColor

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.backgroundColor = .clear
        view.isEditable = false
        view.isSelectable = true
        view.isScrollEnabled = false
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.textContainer.lineBreakMode = .byWordWrapping
        view.dataDetectorTypes = []
        view.adjustsFontForContentSizeCategory = true
        // Keep system copy/lookup menu (partial selection, iPad right-click).
        view.isUserInteractionEnabled = true
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        let attrs: [NSAttributedString.Key: Any] = [
            .font: uiFont,
            .foregroundColor: color,
        ]
        view.attributedText = NSAttributedString(string: text, attributes: attrs)
        view.invalidateIntrinsicContentSize()
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let width = proposal.width ?? UIScreen.main.bounds.width
        let fitting = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: width, height: fitting.height)
    }
}

private extension Font.Weight {
    var uiWeight: UIFont.Weight {
        switch self {
        case .ultraLight: return .ultraLight
        case .thin: return .thin
        case .light: return .light
        case .regular: return .regular
        case .medium: return .medium
        case .semibold: return .semibold
        case .bold: return .bold
        case .heavy: return .heavy
        case .black: return .black
        default: return .regular
        }
    }
}
