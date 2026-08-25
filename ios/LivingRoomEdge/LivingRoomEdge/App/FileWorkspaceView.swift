import SwiftUI
import UniformTypeIdentifiers
import UIKit

/// Local file inbox: pick from Files / iCloud / device, upload as Asset. Not a camera CTA.
struct FileWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @StateObject private var clicks = ClickGuard()
    @State private var showPicker = false
    @State private var notice = ""

    var body: some View {
        ZStack {
            EdgeTheme.canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        EdgeTheme.heroTitle("文件")
                        EdgeTheme.heroSubtitle("从「文件」App、iCloud 或本机选取，上传后登记为 Asset。不经意图理解。")
                    }
                    .padding(.top, 8)

                    pickCard

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
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 36)
            }
        }
        .fileImporter(
            isPresented: $showPicker,
            allowedContentTypes: [.item],
            allowsMultipleSelection: false
        ) { result in
            handlePick(result)
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
                    Text("PDF、图片、表格、文本…")
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
        .accessibilityHint("打开系统文件选择器")
    }

    @ViewBuilder
    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("最近文件")
            if model.fileTurns.isEmpty {
                Text("还没有上传过文件。点上方卡片从系统文件选择器选取。")
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
        showPicker = true
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
