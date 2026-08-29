import SwiftUI

/// Shared Markdown reader: soft background, font scale, TOC — used by Docs detail and Chat inline sheet.
struct MarkdownReaderView: View {
    let markdown: String

    @AppStorage(DevMarkdownFontScaleStore.key) private var fontScale: Double = DevMarkdownFontScaleStore.defaultScale
    @State private var showTOC = false

    private let blocks: [DevMarkdownBlock]
    private let outline: [DevMarkdownOutlineItem]

    init(markdown: String) {
        self.markdown = markdown
        blocks = DevMarkdownParser.parse(markdown)
        outline = DevMarkdownOutline.items(from: blocks)
    }

    private var readingStyle: DevMarkdownReadingStyle {
        DevMarkdownReadingStyle(
            palette: .paperDark,
            fontScale: CGFloat(fontScale),
            lineSpacing: 5
        )
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                MarkdownDocumentView(blocks: blocks)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 16)
            }
            .background(readingStyle.palette.canvas)
            .environment(\.devMarkdownReadingStyle, readingStyle)
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    if !outline.isEmpty {
                        Button {
                            showTOC = true
                        } label: {
                            Label("目录", systemImage: "list.bullet.indent")
                        }
                        .foregroundStyle(readingStyle.palette.accent)
                    }
                    fontScaleControls
                }
            }
            .sheet(isPresented: $showTOC) {
                DevMarkdownTOCSheet(
                    items: outline,
                    palette: readingStyle.palette,
                    onSelect: { item in
                        showTOC = false
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                            withAnimation(.easeInOut(duration: 0.25)) {
                                proxy.scrollTo(item.id, anchor: .top)
                            }
                        }
                    }
                )
            }
        }
    }

    private var fontScaleControls: some View {
        HStack(spacing: 6) {
            Button {
                fontScale = DevMarkdownFontScaleStore.clamp(fontScale - DevMarkdownFontScaleStore.step)
            } label: {
                Image(systemName: "textformat.size.smaller")
            }
            .disabled(fontScale <= DevMarkdownFontScaleStore.minScale)

            Text(DevMarkdownFontScaleStore.label(for: fontScale))
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(readingStyle.palette.dim)
                .frame(minWidth: 28)

            Button {
                fontScale = DevMarkdownFontScaleStore.clamp(fontScale + DevMarkdownFontScaleStore.step)
            } label: {
                Image(systemName: "textformat.size.larger")
            }
            .disabled(fontScale >= DevMarkdownFontScaleStore.maxScale)
        }
        .foregroundStyle(readingStyle.palette.accent)
        .buttonStyle(.plain)
    }
}

struct MarkdownDocumentView: View {
    private let blocks: [DevMarkdownBlock]

    init(markdown: String) {
        blocks = DevMarkdownParser.parse(markdown)
    }

    fileprivate init(blocks: [DevMarkdownBlock]) {
        self.blocks = blocks
    }

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                DevMarkdownBlockView(block: block, blockIndex: index)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }
}

private struct DevMarkdownTOCSheet: View {
    let items: [DevMarkdownOutlineItem]
    let palette: DevMarkdownReadingPalette
    var onSelect: (DevMarkdownOutlineItem) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                ForEach(items) { item in
                    Button {
                        onSelect(item)
                    } label: {
                        HStack(spacing: 0) {
                            Text(item.title)
                                .font(.system(
                                    size: tocFontSize(item.level),
                                    weight: item.level == 1 ? .semibold : .regular,
                                    design: .rounded
                                ))
                                .foregroundStyle(item.level == 1 ? palette.heading : palette.text)
                                .lineLimit(2)
                                .padding(.leading, CGFloat(item.level - 1) * 14)
                        }
                        .padding(.vertical, 4)
                    }
                    .listRowBackground(palette.codeBackground)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(palette.canvas.ignoresSafeArea())
            .navigationTitle("目录")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(palette.canvas, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                        .foregroundStyle(palette.accent)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private func tocFontSize(_ level: Int) -> CGFloat {
        switch level {
        case 1: return 16
        case 2: return 15
        default: return 14
        }
    }
}

private struct DevMarkdownBlockView: View {
    @Environment(\.devMarkdownReadingStyle) private var style
    let block: DevMarkdownBlock
    let blockIndex: Int

    var body: some View {
        Group {
            switch block {
            case .heading(let level, let inlines):
                DevMarkdownInlineText(inlines: inlines, role: headingRole(level))
                    .padding(.top, level == 1 ? 8 : 14)
                    .padding(.bottom, 6)
                    .id(DevMarkdownAnchor.heading(blockIndex))
            case .paragraph(let inlines):
                DevMarkdownInlineText(inlines: inlines, role: .body)
                    .padding(.vertical, 6)
            case .unorderedList(let items):
                VStack(alignment: .leading, spacing: 8 * style.fontScale) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top, spacing: 10) {
                            Text("•")
                                .font(.system(size: style.scaledBodySize(16), weight: .bold, design: .rounded))
                                .foregroundStyle(style.palette.accent.opacity(0.9))
                                .padding(.top, 2)
                            DevMarkdownInlineText(inlines: item, role: .body)
                        }
                    }
                }
                .padding(.vertical, 8)
            case .orderedList(let items):
                VStack(alignment: .leading, spacing: 8 * style.fontScale) {
                    ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                        HStack(alignment: .top, spacing: 10) {
                            Text("\(index + 1).")
                                .font(.system(size: style.scaledBodySize(16), weight: .semibold, design: .rounded))
                                .foregroundStyle(style.palette.accent.opacity(0.9))
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
                            .font(.system(size: style.scaledBodySize(11), weight: .semibold, design: .monospaced))
                            .foregroundStyle(style.palette.dim)
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        Text(code)
                            .font(.system(size: style.scaledBodySize(14), weight: .regular, design: .monospaced))
                            .foregroundStyle(style.palette.text.opacity(0.95))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(14)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(style.palette.codeBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(style.palette.codeBorder, lineWidth: 1)
                        )
                )
                .padding(.vertical, 10)
            case .blockquote(let inner):
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(inner.enumerated()), id: \.offset) { idx, child in
                        DevMarkdownBlockView(block: child, blockIndex: blockIndex * 1000 + idx)
                    }
                }
                .padding(.leading, 14)
                .padding(.vertical, 8)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(style.palette.quoteBar)
                        .frame(width: 3)
                }
                .foregroundStyle(style.palette.text.opacity(0.88))
            case .table(let headers, let rows):
                DevMarkdownTableView(headers: headers, rows: rows)
                    .padding(.vertical, 10)
            case .divider:
                Rectangle()
                    .fill(style.palette.codeBorder)
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
    @Environment(\.devMarkdownReadingStyle) private var style
    let inlines: [DevMarkdownInline]
    let role: DevMarkdownTextRole

    var body: some View {
        Text(attributed)
            .lineSpacing(style.scaledLineSpacing())
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
                run.backgroundColor = UIColor(style.palette.codeBackground)
                run.foregroundColor = UIColor(style.palette.text.opacity(0.95))
            case .link(let url):
                if let link = URL(string: url) ?? URL(string: url.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed) ?? url) {
                    run.link = link
                }
                run.foregroundColor = UIColor(style.palette.accent)
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
        let base: CGFloat = switch role {
        case .h1: 26
        case .h2: 21
        case .h3: 18
        case .body: 16
        }
        return style.scaledBodySize(base)
    }

    private var textColor: Color {
        switch role {
        case .h1: return style.palette.heading
        case .h2, .h3: return style.palette.headingMuted
        case .body: return style.palette.text
        }
    }

    private var baseUIFont: UIFont {
        let weight: UIFont.Weight = switch role {
        case .h1: .bold
        case .h2, .h3: .semibold
        case .body: .regular
        }
        let base = UIFont.systemFont(ofSize: bodySize, weight: weight)
        if let rounded = base.fontDescriptor.withDesign(.rounded) {
            return UIFont(descriptor: rounded, size: bodySize)
        }
        return base
    }
}

private struct DevMarkdownTableView: View {
    @Environment(\.devMarkdownReadingStyle) private var style
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
                        .background(index.isMultiple(of: 2) ? Color.clear : style.palette.tableStripe)
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(style.palette.codeBorder, lineWidth: 1)
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
                    .font(.system(
                        size: style.scaledBodySize(isHeader ? 13 : 14),
                        weight: isHeader ? .semibold : .regular,
                        design: .rounded
                    ))
                    .foregroundStyle(isHeader ? style.palette.heading : style.palette.text)
                    .multilineTextAlignment(.leading)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .frame(minWidth: 96, alignment: .leading)
                if index < cells.count - 1 {
                    Rectangle()
                        .fill(style.palette.codeBorder)
                        .frame(width: 1)
                }
            }
        }
        .background(isHeader ? style.palette.codeBackground : Color.clear)
        .overlay(alignment: .bottom) {
            if isHeader {
                Rectangle()
                    .fill(style.palette.codeBorder)
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
