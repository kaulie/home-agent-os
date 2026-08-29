import SwiftUI

struct ChatMessageBodyView: View {
    let bodyText: String
    let textColor: Color
    let linkColor: Color
    var allowsTextSelection = false
    var onOpenDoc: (String) -> Void

    var body: some View {
        let text = Text(ChatDocReference.attributedBody(bodyText, textColor: textColor, linkColor: linkColor))
            .font(.system(size: 15, design: .rounded))
            .environment(\.openURL, OpenURLAction { url in
                if let path = ChatDocReference.path(from: url) {
                    onOpenDoc(path)
                    return .handled
                }
                return .systemAction
            })
        if allowsTextSelection {
            text.textSelection(.enabled)
        } else {
            text
        }
    }
}

struct InlineDocSheet: View {
    @EnvironmentObject private var store: DevStore
    @Environment(\.dismiss) private var dismiss
    let docPath: String

    @State private var doc: DevDocContent?
    @State private var error = ""
    @State private var loading = true

    private let palette = DevMarkdownReadingPalette.paperDark

    private var title: String {
        ChatDocReference.label(path: docPath)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                palette.canvas.ignoresSafeArea()
                Group {
                    if loading {
                        ProgressView("读取 \(docPath)…")
                            .tint(palette.accent)
                    } else if !error.isEmpty {
                        Text(error)
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(DevTheme.off)
                            .padding()
                    } else if let doc {
                        MarkdownReaderView(markdown: doc.content)
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .devMarkdownReadingChrome(palette: palette)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                        .foregroundStyle(palette.accent)
                }
            }
            .task(id: docPath) {
                loading = true
                error = ""
                do {
                    doc = try await store.fetchDoc(path: docPath)
                } catch {
                    self.error = error.localizedDescription
                }
                loading = false
            }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }
}

struct ChatDocPickerSheet: View {
    @EnvironmentObject private var store: DevStore
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var onPick: (DevDocEntry) -> Void

    var body: some View {
        NavigationStack {
            List {
                if let err = store.docsError, !err.isEmpty {
                    Text(err)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.off)
                }
                ForEach(filtered) { entry in
                    Button {
                        onPick(entry)
                        dismiss()
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(entry.title)
                                .font(.system(size: 16, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.mist)
                            Text(entry.path)
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundStyle(DevTheme.dim)
                        }
                        .padding(.vertical, 4)
                    }
                    .listRowBackground(DevTheme.panel)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(DevTheme.ink.ignoresSafeArea())
            .searchable(text: $query, prompt: "搜索文档")
            .navigationTitle("引用文档")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
            .task {
                await store.loadDocs(showSpinner: true)
            }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }

    private var filtered: [DevDocEntry] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if q.isEmpty { return store.docsEntries }
        return store.docsEntries.filter {
            $0.path.lowercased().contains(q) || $0.title.lowercased().contains(q)
        }
    }
}
