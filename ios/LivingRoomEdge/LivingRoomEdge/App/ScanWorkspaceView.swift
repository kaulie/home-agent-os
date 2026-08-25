import SwiftUI
import UIKit

/// Disk cache for local document-scan JPEGs (display only; capture stays in VisualInput).
enum ScanPreviewStore {
    private static let folderName = "scan-previews"
    private static let maxFiles = 40

    static func save(assetId: String, image: UIImage) {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty, let data = image.jpegData(compressionQuality: 0.92) else { return }
        let dir = directory()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? data.write(to: fileURL(aid), options: .atomic)
        prune()
    }

    static func image(for assetId: String) -> UIImage? {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty,
              let data = try? Data(contentsOf: fileURL(aid)),
              let image = UIImage(data: data) else {
            return nil
        }
        return image
    }

    static func remove(assetId: String) {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty else { return }
        try? FileManager.default.removeItem(at: fileURL(aid))
    }

    private static func directory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent(folderName, isDirectory: true)
    }

    private static func fileURL(_ assetId: String) -> URL {
        let safe = assetId.replacingOccurrences(of: "/", with: "_")
        return directory().appendingPathComponent("\(safe).jpg")
    }

    private static func prune() {
        let dir = directory()
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        ) else { return }
        let ranked = files.compactMap { url -> (URL, Date)? in
            let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
                ?? .distantPast
            return (url, date)
        }
        .sorted { $0.1 > $1.1 }
        for extra in ranked.dropFirst(maxFiles) {
            try? FileManager.default.removeItem(at: extra.0)
        }
    }
}

/// Dedicated scan workspace. CTA presents the existing VisionKit scanner; this view does not capture.
struct ScanWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @StateObject private var clicks = ClickGuard()

    var body: some View {
        ZStack {
            EdgeTheme.canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    VStack(alignment: .leading, spacing: 8) {
                        EdgeTheme.heroTitle("扫描")
                        EdgeTheme.heroSubtitle("纸质小票、文档：立刻打开系统扫描仪，完成后自动上传并登记 Asset。不经意图理解。")
                    }
                    .padding(.top, 8)

                    if VisualInput.isSupported {
                        scanCTA
                    } else {
                        EdgeEmptyPlaceholder(
                            title: "本机不支持系统文档扫描",
                            detail: "需要 VisionKit 文档扫描仪（真机）。模拟器无法打开系统扫描。"
                        )
                    }

                    if !model.scanHint.isEmpty {
                        Text(model.scanHint)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(Color.orange.opacity(0.95))
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    recentSection
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 36)
            }
        }
    }

    private var scanCTA: some View {
        Button {
            startScan()
        } label: {
            VStack(spacing: 12) {
                if model.scanBusy {
                    ProgressView()
                        .tint(EdgeTheme.sand)
                        .scaleEffect(1.15)
                    Text("正在上传…")
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                    Text("扫描图登记中")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                } else {
                    Image(systemName: "doc.viewfinder")
                        .font(.system(size: 44, weight: .light))
                    Text("开始扫描")
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                    Text("打开系统扫描仪")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
            }
            .foregroundStyle(EdgeTheme.sand)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 36)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(EdgeTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(EdgeTheme.sand.opacity(0.35), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
        .disabled(model.scanBusy)
        .accessibilityLabel(model.scanBusy ? "正在上传扫描图" : "开始扫描")
        .accessibilityHint("打开系统文档扫描仪")
    }

    @ViewBuilder
    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("最近扫描")
            if model.scanTurns.isEmpty {
                Text("还没有扫描图。点上方按钮打开系统扫描仪。")
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            } else {
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(model.scanTurns) { turn in
                        MediaTimelineRow(turn: turn, accessibilityNoun: "扫描图")
                    }
                }
            }
        }
    }

    private func startScan() {
        guard clicks.tryTap(cooldown: 1.0) else { return }
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setScanHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        guard VisualInput.isSupported else {
            model.setScanHint("本机不支持系统文档扫描")
            return
        }
        Task {
            await model.runLocalDocumentScan(serverURL: server)
        }
    }
}

struct MediaTimelineRow: View {
    let turn: ChatTurn
    var accessibilityNoun: String = "扫描图"
    /// Retry hook for a failed background upload (photo rows only).
    var onRetryUpload: (() -> Void)? = nil
    @State private var image: UIImage?
    @State private var showFull = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(Self.timeLabel(turn.createdAt))
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(EdgeTheme.dim)
            Button {
                if image != nil { showFull = true }
            } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(EdgeTheme.panel)
                    if let image {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Image(systemName: "doc")
                            .font(.title)
                            .foregroundStyle(EdgeTheme.dim)
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: 220)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(EdgeTheme.panelStroke, lineWidth: 1)
                )
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(accessibilityNoun) \(Self.timeLabel(turn.createdAt))")
            if let status = turn.uploadStatus {
                uploadLine(status)
            }
        }
        .task(id: turn.inputAssetId) {
            if let aid = turn.inputAssetId {
                image = ScanPreviewStore.image(for: aid)
            }
        }
        .fullScreenCover(isPresented: $showFull) {
            if let image {
                ImageLightbox(image: image)
            }
        }
    }

    /// Per-photo background upload state. Capture itself is already acknowledged
    /// by the row being in the list; this line only reports the upload step.
    @ViewBuilder
    private func uploadLine(_ status: LocalMediaUploadStatus) -> some View {
        switch status {
        case .pending:
            Label("等待上传…", systemImage: "clock")
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(EdgeTheme.dim)
        case .uploading:
            HStack(spacing: 8) {
                ProgressView()
                    .scaleEffect(0.7)
                    .frame(width: 14, height: 14)
                Text("上传中…")
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            }
        case .uploaded:
            Label("已上传", systemImage: "checkmark.circle.fill")
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(EdgeTheme.sand)
        case .failed:
            VStack(alignment: .leading, spacing: 6) {
                Text(turn.assistantText ?? "上传失败（照片已存本机）")
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(Color.orange.opacity(0.95))
                    .fixedSize(horizontal: false, vertical: true)
                if let onRetryUpload {
                    Button("重试上传", action: onRetryUpload)
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.sand)
                        .accessibilityLabel("重试上传这张\(accessibilityNoun)")
                }
            }
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
