import SwiftUI

struct DocsConsoleView: View {
    @EnvironmentObject private var store: DevStore
    @State private var query = ""

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    Group {
                        if store.isLoadingDocs && store.docsEntries.isEmpty {
                            ProgressView("加载文档…")
                                .tint(DevTheme.sand)
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                        } else {
                            List {
                                if let err = store.docsError, !err.isEmpty {
                                    Section {
                                        Text(err)
                                            .font(.system(size: 13, design: .rounded))
                                            .foregroundStyle(DevTheme.off)
                                    }
                                    .listRowBackground(DevTheme.panel)
                                }
                                Section {
                                    ForEach(filteredEntries) { entry in
                                        NavigationLink(value: entry) {
                                            docRow(entry)
                                        }
                                    }
                                } header: {
                                    Text("项目 Markdown")
                                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                                        .foregroundStyle(DevTheme.sand.opacity(0.85))
                                }
                                .listRowBackground(DevTheme.panel)
                            }
                            .listStyle(.insetGrouped)
                            .scrollContentBackground(.hidden)
                        }
                    }
                }
            }
            .navigationTitle("文档")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .searchable(text: $query, prompt: "搜索文档")
            .navigationDestination(for: DevDocEntry.self) { entry in
                DocDetailView(entry: entry)
            }
            .refreshable {
                await store.loadDocs(showSpinner: false)
            }
            .task {
                await store.loadDocs(showSpinner: true)
            }
        }
    }

    private var filteredEntries: [DevDocEntry] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return store.docsEntries }
        return store.docsEntries.filter {
            $0.path.lowercased().contains(q) || $0.title.lowercased().contains(q)
        }
    }

    private func docRow(_ entry: DevDocEntry) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(entry.title)
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.mist)
            Text(entry.path)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(DevTheme.dim)
        }
        .padding(.vertical, 4)
    }
}

private struct DocDetailView: View {
    @EnvironmentObject private var store: DevStore
    let entry: DevDocEntry
    @State private var doc: DevDocContent?
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        ZStack {
            DevTheme.ink.ignoresSafeArea()
            Group {
                if loading {
                    ProgressView("读取 \(entry.path)…")
                        .tint(DevTheme.sand)
                } else if !error.isEmpty {
                    Text(error)
                        .font(.system(size: 14, design: .rounded))
                        .foregroundStyle(DevTheme.off)
                        .padding()
                } else if let doc {
                    ScrollView {
                        MarkdownDocumentView(markdown: doc.content)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(16)
                    }
                }
            }
        }
        .navigationTitle(entry.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(DevTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .task(id: entry.path) {
            loading = true
            error = ""
            do {
                doc = try await store.fetchDoc(path: entry.path)
            } catch {
                self.error = error.localizedDescription
            }
            loading = false
        }
    }
}
