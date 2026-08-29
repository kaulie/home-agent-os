import SwiftUI

struct MarkdownDocumentView: View {
    private let blocks: [DevMarkdownBlock]

    init(markdown: String) {
        blocks = DevMarkdownParser.parse(markdown)
    }

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                DevMarkdownBlockView(block: block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }
}

private struct DevMarkdownBlockView: View {
    let block: DevMarkdownBlock

    var body: some View {
        Group {
            switch block {
            case .heading(let level, let inlines):
                DevMarkdownInlineText(inlines: inlines, role: headingRole(level))
                    .padding(.top, level == 1 ? 8 : 14)
                    .padding(.bottom, 6)
            case .paragraph(let inlines):
                DevMarkdownInlineText(inlines: inlines, role: .body)
                    .padding(.vertical, 6)
            case .unorderedList(let items):
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top, spacing: 10) {
                            Text("•")
                                .font(.system(size: 16, weight: .bold, design: .rounded))
                                .foregroundStyle(DevTheme.sand.opacity(0.9))
                                .padding(.top, 2)
                            DevMarkdownInlineText(inlines: item, role: .body)
                        }
                    }
                }
                .padding(.vertical, 8)
            case .orderedList(let items):
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                        HStack(alignment: .top, spacing: 10) {
                            Text("\(index + 1).")
                                .font(.system(size: 16, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.sand.opacity(0.9))
                                .frame(minWidth: 24, alignment: .trailing)
                            DevMarkdownInlineText(inlines: item, role: .body)
                        }
                    }
                }
                .padding(.vertical, 8)
            case .codeBlock(let language, let code):
                VStack(alignment: .leading, spacing: 8) {
                    if let language, !language.isEmpty {
                        Text(language.uppercased())
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(DevTheme.dim)
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        Text(code)
                            .font(.system(size: 14, weight: .regular, design: .monospaced))
                            .foregroundStyle(DevTheme.mist.opacity(0.95))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(14)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(DevTheme.panel)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(DevTheme.panelStroke, lineWidth: 1)
                        )
                )
                .padding(.vertical, 10)
            case .blockquote(let inner):
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(inner.enumerated()), id: \.offset) { _, child in
                        DevMarkdownBlockView(block: child)
                    }
                }
                .padding(.leading, 14)
                .padding(.vertical, 8)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(DevTheme.sand.opacity(0.55))
                        .frame(width: 3)
                }
                .foregroundStyle(DevTheme.mist.opacity(0.88))
            case .table(let headers, let rows):
                DevMarkdownTableView(headers: headers, rows: rows)
                    .padding(.vertical, 10)
            case .divider:
                Rectangle()
                    .fill(DevTheme.panelStroke)
                    .frame(height: 1)
                    .padding(.vertical, 14)
            }
        }
    }

    private func headingRole(_ level: Int) -> DevMarkdownTextRole {
        switch level {
        case 1: return .h1
        case 2: return .h2
        default: return .h3
        }
    }
}

private enum DevMarkdownTextRole {
    case h1, h2, h3, body
}

private struct DevMarkdownInlineText: View {
    let inlines: [DevMarkdownInline]
    let role: DevMarkdownTextRole

    var body: some View {
        Text(attributed)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var attributed: AttributedString {
        var result = AttributedString()
        for inline in inlines {
            var run = AttributedString(inline.text)
            applyBaseStyle(&run)
            switch inline.style {
            case .plain:
                break
            case .bold:
                run.font = baseUIFont.withWeight(.bold)
            case .italic:
                run.font = baseUIFont.withTraits(.traitItalic)
            case .code:
                run.font = .monospacedSystemFont(ofSize: bodySize - 1, weight: .medium)
                run.backgroundColor = UIColor(DevTheme.chip)
                run.foregroundColor = UIColor(DevTheme.mist.opacity(0.95))
            case .link(let url):
                if let link = URL(string: url) ?? URL(string: url.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed) ?? url) {
                    run.link = link
                }
                run.foregroundColor = UIColor(DevTheme.sand)
                run.underlineStyle = .single
            }
            result.append(run)
        }
        return result
    }

    private func applyBaseStyle(_ run: inout AttributedString) {
        run.font = baseUIFont
        run.foregroundColor = UIColor(textColor)
    }

    private var bodySize: CGFloat {
        switch role {
        case .h1: return 26
        case .h2: return 21
        case .h3: return 18
        case .body: return 16
        }
    }

    private var textColor: Color {
        switch role {
        case .h1: return DevTheme.sand
        case .h2, .h3: return DevTheme.mist.opacity(0.95)
        case .body: return DevTheme.mist
        }
    }

    private var baseUIFont: UIFont {
        let weight: UIFont.Weight = {
            switch role {
            case .h1: return .bold
            case .h2, .h3: return .semibold
            case .body: return .regular
            }
        }()
        let size = bodySize
        let base = UIFont.systemFont(ofSize: size, weight: weight)
        if let rounded = base.fontDescriptor.withDesign(.rounded) {
            return UIFont(descriptor: rounded, size: size)
        }
        return base
    }
}

private struct DevMarkdownTableView: View {
    let headers: [String]
    let rows: [[String]]

    private var columnCount: Int {
        max(headers.count, rows.map(\.count).max() ?? 0)
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 0) {
                tableRow(cells: padded(headers), isHeader: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    tableRow(cells: padded(row), isHeader: false)
                        .background(index.isMultiple(of: 2) ? Color.clear : DevTheme.panel.opacity(0.45))
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(DevTheme.panelStroke, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }

    private func padded(_ cells: [String]) -> [String] {
        var out = cells
        while out.count < columnCount { out.append("") }
        return Array(out.prefix(columnCount))
    }

    private func tableRow(cells: [String], isHeader: Bool) -> some View {
        HStack(spacing: 0) {
            ForEach(Array(cells.enumerated()), id: \.offset) { index, cell in
                Text(cell)
                    .font(.system(size: isHeader ? 13 : 14, weight: isHeader ? .semibold : .regular, design: .rounded))
                    .foregroundStyle(isHeader ? DevTheme.sand.opacity(0.95) : DevTheme.mist)
                    .multilineTextAlignment(.leading)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .frame(minWidth: 96, alignment: .leading)
                if index < cells.count - 1 {
                    Rectangle()
                        .fill(DevTheme.panelStroke)
                        .frame(width: 1)
                }
            }
        }
        .background(isHeader ? DevTheme.panel : Color.clear)
        .overlay(alignment: .bottom) {
            if isHeader {
                Rectangle()
                    .fill(DevTheme.panelStroke)
                    .frame(height: 1)
            }
        }
    }
}

private extension UIFont {
    func withTraits(_ traits: UIFontDescriptor.SymbolicTraits) -> UIFont {
        guard let descriptor = fontDescriptor.withSymbolicTraits(traits) else { return self }
        return UIFont(descriptor: descriptor, size: pointSize)
    }

    func withWeight(_ weight: UIFont.Weight) -> UIFont {
        let base = UIFont.systemFont(ofSize: pointSize, weight: weight)
        if let rounded = base.fontDescriptor.withDesign(.rounded) {
            return UIFont(descriptor: rounded, size: pointSize)
        }
        return base
    }
}
