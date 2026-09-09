import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import UIKit

/// Local file inbox: pick from Photos album, Files / iCloud / device; upload as Asset.
struct FileWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @StateObject private var clicks = ClickGuard()
    @State private var showSourceMenu = false
    @State private var showFilePicker = false
    @State private var photoItem: PhotosPickerItem?
    @State private var showPhotoPicker = false
    @State private var showURLAlert = false
    @State private var urlInput = ""
    @State private var notice = ""
    @StateObject private var urlStore = SavedUrlAssetStore()

    var body: some View {
        ZStack {
            EdgeTheme.canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        EdgeTheme.heroTitle("文件")
                        EdgeTheme.heroSubtitle("可从相册选图，或从「文件」App / iCloud / 本机选取，上传后登记为 Asset。不经意图理解。")
                    }
                    .padding(.top, 8)

                    pickCard

                    saveURLCard

                    if !model.fileHint.isEmpty {
                        Text(model.fileHint)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(Color.orange.opacity(0.95))
                            .fixedSize(horizontal: false, vertical: true)
                    } else if !notice.isEmpty {
                        Text(notice)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(EdgeTheme.sand)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    recentSection

                    savedLinksSection
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 36)
            }
        }
        .confirmationDialog("选择来源", isPresented: $showSourceMenu, titleVisibility: .visible) {
            Button("相册照片") {
                showPhotoPicker = true
            }
            Button("文件 App / iCloud") {
                showFilePicker = true
            }
            Button("取消", role: .cancel) {}
        }
        .photosPicker(
            isPresented: $showPhotoPicker,
            selection: $photoItem,
            matching: .images,
            photoLibrary: .shared()
        )
        .onChange(of: photoItem) { _, item in
            guard let item else { return }
            Task { await handlePhotoItem(item) }
        }
        .fileImporter(
            isPresented: $showFilePicker,
            allowedContentTypes: [.item],
            allowsMultipleSelection: false
        ) { result in
            handlePick(result)
        }
        .alert("保存链接", isPresented: $showURLAlert) {
            TextField("网址，如 https://…", text: $urlInput)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .autocorrectionDisabled()
            Button("保存") {
                let trimmed = urlInput.trimmingCharacters(in: .whitespacesAndNewlines)
                urlInput = ""
                guard !trimmed.isEmpty else {
                    notice = "网址不能为空。"
                    return
                }
                Task { await saveURL(trimmed) }
            }
            Button("取消", role: .cancel) {
                urlInput = ""
            }
        } message: {
            Text("粘贴一个网页链接，登记为 Brain 的 url 资产（不转文档）。")
        }
    }

    private var pickCard: some View {
        Button {
            beginPick()
        } label: {
            VStack(spacing: 12) {
                if model.fileBusy {
                    ProgressView()
                        .tint(EdgeTheme.sand)
                        .scaleEffect(1.15)
                    Text("正在上传…")
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                    Text(model.fileUploadingName.isEmpty ? "登记 Asset 中" : model.fileUploadingName)
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                } else {
                    Image(systemName: "folder.badge.plus")
                        .font(.system(size: 44, weight: .light))
                    Text("选择文件")
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                    Text("相册 · PDF · 图片 · 表格 · 文本…")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
            }
            .foregroundStyle(EdgeTheme.sand)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 36)
            .padding(.horizontal, 16)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(EdgeTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(
                                EdgeTheme.sand.opacity(model.fileBusy ? 0.22 : 0.45),
                                style: StrokeStyle(lineWidth: 1.2, dash: [7, 5])
                            )
                    )
            )
        }
        .buttonStyle(.plain)
        .disabled(model.fileBusy)
        .accessibilityLabel(model.fileBusy ? "正在上传文件" : "选择文件")
        .accessibilityHint("可从相册或系统文件选择器选取")
    }

    private var saveURLCard: some View {
        Button {
            guard clicks.tryTap(cooldown: 0.8) else { return }
            beginSaveURL()
        } label: {
            VStack(spacing: 12) {
                Image(systemName: "link.badge.plus")
                    .font(.system(size: 38, weight: .light))
                Text("保存链接")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                Text("粘贴/输入网址，登记为 Brain 的 url 资产（不转文档）。存好后可让助手把它抓成 PDF / 文本。")
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.mist)
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(EdgeTheme.sand)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 22)
            .padding(.horizontal, 16)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(EdgeTheme.panel)
            )
        }
        .buttonStyle(.plain)
        .disabled(model.fileBusy)
        .accessibilityLabel("保存链接")
    }

    @ViewBuilder
    private var savedLinksSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("已存链接")
            if urlStore.items.isEmpty {
                Text("还没有保存过链接。点上方「保存链接」，粘贴一条网址即可。")
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            } else {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(urlStore.items) { item in
                        SavedUrlRow(
                            item: item,
                            onDelete: { id in
                                urlStore.remove(id: id)
                            },
                            onNotice: { message in
                                notice = message
                            }
                        )
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("最近文件")
            if model.fileTurns.isEmpty {
                Text("还没有上传过文件。点上方卡片，可选相册照片或系统文件。")
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            } else {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(model.fileTurns) { turn in
                        FileInboxRow(turn: turn) { message in
                            notice = message
                        }
                    }
                }
            }
        }
    }

    private func beginPick() {
        guard clicks.tryTap(cooldown: 0.8) else { return }
        notice = ""
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setFileHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        model.setFileHint("")
        showSourceMenu = true
    }

    private func beginSaveURL() {
        notice = ""
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setFileHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        model.setFileHint("")
        urlInput = ""
        showURLAlert = true
    }

    private func saveURL(_ raw: String) async {
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            await MainActor.run {
                model.setFileHint("请先在设置里填写 Brain URL")
                showSettings = true
            }
            return
        }
        let normalized = Self.normalizedLink(raw)
        do {
            let result = try await VisualInput.registerURLAsset(
                url: normalized,
                title: "",
                intentURL: server
            )
            await MainActor.run {
                urlStore.add(
                    SavedUrlAsset(
                        id: UUID(),
                        assetId: result.assetId,
                        url: result.url,
                        title: result.title,
                        createdAt: Date()
                    )
                )
                notice = "已保存链接 · \(result.assetId)"
            }
        } catch let e as VisualInput.InputError {
            await MainActor.run { notice = e.localizedDescription }
        } catch {
            await MainActor.run { notice = error.localizedDescription }
        }
    }

    /// 没写协议时补 https://，避免用户只粘域名。
    private static func normalizedLink(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.contains("://") { return trimmed }
        return "https://" + trimmed
    }

    private func handlePick(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !server.isEmpty else {
                model.setFileHint("请先在设置里填写 Brain URL")
                showSettings = true
                return
            }
            Task {
                await model.runLocalFileUpload(url: url, serverURL: server)
            }
        case .failure:
            break
        }
    }

    private func handlePhotoItem(_ item: PhotosPickerItem) async {
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            await MainActor.run {
                model.setFileHint("请先在设置里填写 Brain URL")
                showSettings = true
                photoItem = nil
            }
            return
        }
        do {
            guard let data = try await item.loadTransferable(type: Data.self), !data.isEmpty else {
                await MainActor.run {
                    model.setFileHint("无法读取相册照片，请重试或改用「文件 App」。")
                    photoItem = nil
                }
                return
            }
            let (payload, filename, mime) = Self.normalizedImageUpload(data: data)
            await model.runLocalFileUpload(
                data: payload,
                filename: filename,
                mimeType: mime,
                serverURL: server
            )
        } catch {
            await MainActor.run {
                model.setFileHint("读取相册失败：\(error.localizedDescription)")
            }
        }
        await MainActor.run {
            photoItem = nil
        }
    }

    /// Prefer JPEG for upload; keep PNG when the album item is clearly PNG.
    private static func normalizedImageUpload(data: Data) -> (Data, String, String) {
        let stamp = Int(Date().timeIntervalSince1970)
        if data.starts(with: [0x89, 0x50, 0x4E, 0x47]) {
            return (data, "album_\(stamp).png", "image/png")
        }
        if let image = UIImage(data: data),
           let jpeg = image.jpegData(compressionQuality: 0.92) {
            return (jpeg, "album_\(stamp).jpg", "image/jpeg")
        }
        return (data, "album_\(stamp).jpg", "image/jpeg")
    }
}

/// 文件页「已存链接」行：点按用系统浏览器打开；左滑删除本机记录（不删 Brain 资产）。
private struct SavedUrlRow: View {
    let item: SavedUrlAsset
    var onDelete: (UUID) -> Void
    var onNotice: (String) -> Void

    @Environment(\.openURL) private var openURL

    var body: some View {
        Button {
            open()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(EdgeTheme.ink.opacity(0.55))
                    Image(systemName: "link")
                        .font(.system(size: 18, weight: .regular))
                        .foregroundStyle(EdgeTheme.sand)
                }
                .frame(width: 44, height: 44)

                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title.isEmpty ? item.url : item.title)
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.white.opacity(0.92))
                        .lineLimit(1)
                    Text("\(Self.timeLabel(item.createdAt)) · \(item.url)")
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Image(systemName: "safari")
                    .font(.system(size: 14, weight: .regular))
                    .foregroundStyle(EdgeTheme.dim)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(EdgeTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(EdgeTheme.panelStroke, lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                onDelete(item.id)
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    private func open() {
        guard let url = URL(string: item.url) else {
            onNotice("链接无效，无法打开。")
            return
        }
        openURL(url)
    }

    private static let todayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM/dd HH:mm"
        return f
    }()

    private static func timeLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) {
            return todayFormatter.string(from: date)
        }
        return dayFormatter.string(from: date)
    }
}
private struct FileInboxRow: View {
    let turn: ChatTurn
    var onNotice: (String) -> Void
    @State private var thumb: UIImage?
    @State private var showFull = false

    var body: some View {
        Button {
            tapRow()
        } label: {
            HStack(spacing: 12) {
                leadingMark
                VStack(alignment: .leading, spacing: 3) {
                    Text(turn.userText)
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.white.opacity(0.92))
                        .lineLimit(1)
                    Text("\(typeLabel) · \(Self.timeLabel(turn.createdAt))")
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(EdgeTheme.dim)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(EdgeTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(EdgeTheme.panelStroke, lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(turn.userText) \(typeLabel) \(Self.timeLabel(turn.createdAt))")
        .task(id: turn.inputAssetId) {
            if assetType == "image", let aid = turn.inputAssetId {
                thumb = ScanPreviewStore.image(for: aid)
            }
        }
        .fullScreenCover(isPresented: $showFull) {
            if let thumb {
                ImageLightbox(image: thumb)
            }
        }
    }

    @ViewBuilder
    private var leadingMark: some View {
        if let thumb {
            Image(uiImage: thumb)
                .resizable()
                .scaledToFill()
                .frame(width: 44, height: 44)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        } else {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(EdgeTheme.ink.opacity(0.55))
                Image(systemName: glyphName)
                    .font(.system(size: 18, weight: .regular))
                    .foregroundStyle(EdgeTheme.sand)
            }
            .frame(width: 44, height: 44)
        }
    }

    private var assetType: String {
        if let text = turn.assistantText,
           let range = text.range(of: " · ", options: .backwards) {
            let raw = String(text[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if ["image", "audio", "video", "document"].contains(raw) {
                return raw
            }
        }
        return VisualInput.inferAssetType(mimeType: "", filename: turn.userText)
    }

    private var typeLabel: String {
        switch assetType {
        case "image": return "图片"
        case "audio": return "音频"
        case "video": return "视频"
        default: return "文档"
        }
    }

    private var glyphName: String {
        let name = turn.userText.lowercased()
        if assetType == "image" { return "photo" }
        if assetType == "audio" { return "waveform" }
        if assetType == "video" { return "film" }
        if name.hasSuffix(".pdf") { return "doc.richtext" }
        if name.hasSuffix(".xls") || name.hasSuffix(".xlsx") || name.hasSuffix(".csv")
            || name.hasSuffix(".numbers") {
            return "tablecells"
        }
        if name.hasSuffix(".txt") || name.hasSuffix(".md") { return "doc.text" }
        return "doc"
    }

    private func tapRow() {
        if assetType == "image", thumb != nil {
            showFull = true
            return
        }
        let aid = (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if aid.isEmpty {
            onNotice("已登记，但没有 asset_id。")
        } else {
            onNotice("已登记 Asset · \(aid)")
        }
    }

    private static let todayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM/dd HH:mm"
        return f
    }()

    private static func timeLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) {
            return todayFormatter.string(from: date)
        }
        return dayFormatter.string(from: date)
    }
}
