import SwiftUI

/// 电视 Tab：PDF 投屏翻页控制面。
///
/// 上一页 / 下一页走 `POST /api/v1/intent` 的 capability+params 直派通路
/// （Brain 不过 LLM，直接单步派发给在线的 display.pdf.page 提供者），
/// 随后轮询 intent_detail 取回 `page` / `page_count` / `status_text` 展示。
struct TVView: View {
    @EnvironmentObject private var model: AppModel

    @State private var busy = false
    @State private var page: Int?
    @State private var pageCount: Int?
    @State private var statusLine = "先在「互动」里说：把 PDF 投到电视上"
    @State private var isError = false
    @State private var pollTask: Task<Void, Never>?

    var body: some View {
        ZStack {
            EdgeTheme.canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    pagePanel
                    controls
                    statusPanel
                }
                .padding(.horizontal, 20)
                .padding(.top, 24)
                .padding(.bottom, 32)
            }
        }
        .onDisappear {
            pollTask?.cancel()
            pollTask = nil
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            EdgeTheme.sectionLabel("TV CAST")
            EdgeTheme.heroTitle("电视")
            EdgeTheme.heroSubtitle("PDF 投屏翻页 · 按钮直派能力，不过大模型，毫秒级下发")
        }
    }

    private var pagePanel: some View {
        EdgePanel {
            VStack(spacing: 6) {
                if let page, let pageCount, pageCount > 0 {
                    Text("第 \(page) 页")
                        .font(.system(size: 44, weight: .semibold, design: .serif))
                        .foregroundStyle(Color.white.opacity(0.94))
                    Text("共 \(pageCount) 页")
                        .font(.system(size: 14, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                } else {
                    Text("—")
                        .font(.system(size: 44, weight: .semibold, design: .serif))
                        .foregroundStyle(Color.white.opacity(0.35))
                    Text("当前没有投屏页码信息")
                        .font(.system(size: 14, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
        }
    }

    private var controls: some View {
        HStack(spacing: 14) {
            pageButton(title: "上一页", systemImage: "chevron.left", action: "prev")
            pageButton(title: "下一页", systemImage: "chevron.right", action: "next")
        }
    }

    private func pageButton(title: String, systemImage: String, action: String) -> some View {
        Button {
            turnPage(action)
        } label: {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 18, weight: .bold))
                Text(title)
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 22)
            .foregroundStyle(busy ? EdgeTheme.dim : EdgeTheme.ink)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(EdgeTheme.sand.opacity(busy ? 0.35 : 1))
            )
        }
        .buttonStyle(.plain)
        .disabled(busy)
    }

    private var statusPanel: some View {
        EdgePanel {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: isError ? "exclamationmark.triangle.fill" : "tv.fill")
                    .foregroundStyle(isError ? Color.orange : EdgeTheme.sand)
                Text(statusLine)
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(isError ? Color.orange.opacity(0.95) : EdgeTheme.mist)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                if busy {
                    ProgressView()
                        .tint(EdgeTheme.sand)
                }
            }
        }
    }

    // MARK: - 直派 + 轮询

    private func turnPage(_ action: String) {
        guard !busy else { return }
        busy = true
        isError = false
        statusLine = action == "next" ? "正在翻下一页…" : "正在翻上一页…"
        pollTask?.cancel()
        let client = model.intentClient
        let serverURL = model.intentServerURL
        let label = action == "next" ? "下一页" : "上一页"
        pollTask = Task { @MainActor in
            let result = await client.dispatch(
                text: label,
                source: "text",
                serverURL: serverURL,
                capability: "display.pdf.page",
                params: ["action": action]
            )
            guard result.ok, let snapshot = result.snapshot else {
                busy = false
                isError = true
                statusLine = "翻页失败：\(Self.firstLine(result.message))"
                return
            }
            await pollTerminal(intentId: snapshot.jobId, serverURL: serverURL, client: client)
        }
    }

    /// 轮询 intent_detail 直到终态（直派正常 < 1s，上限 ~10s 兜底）。
    private func pollTerminal(intentId: String, serverURL: String, client: IntentClient) async {
        var last: IntentJobSnapshot?
        for _ in 0 ..< 20 {
            if Task.isCancelled { return }
            if let snap = await client.fetchIntentDetail(intentId: intentId, intentURL: serverURL) {
                last = snap
                if snap.wireStatus.isTerminal { break }
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        guard !Task.isCancelled else { return }
        busy = false
        guard let snap = last else {
            isError = true
            statusLine = "翻页结果查询失败：拿不到 intent 详情"
            return
        }
        apply(snapshot: snap)
    }

    private func apply(snapshot: IntentJobSnapshot) {
        let step = snapshot.planSteps.first(where: { $0.capability == "display.pdf.page" })
        if let outputs = step?.realizedOutputs {
            if let p = Int(outputs["page"] ?? ""), p > 0 { page = p }
            if let n = Int(outputs["page_count"] ?? ""), n > 0 { pageCount = n }
            if let text = outputs["status_text"], !text.isEmpty {
                statusLine = text
                isError = false
                return
            }
        }
        if snapshot.wireStatus == .failed {
            isError = true
            statusLine = "翻页失败：\(snapshot.error ?? step?.runDetail ?? "未知原因")"
        } else if snapshot.wireStatus.isTerminal {
            isError = false
            statusLine = page.map { "已翻到第 \($0) 页" } ?? "翻页完成"
        } else {
            // 轮询超时仍未终态：不报错，提示稍后看电视
            isError = false
            statusLine = "已下发，电视响应稍慢，请稍候"
        }
    }

    private static func firstLine(_ text: String) -> String {
        let line = text.components(separatedBy: .newlines).first ?? text
        return String(line.prefix(160))
    }
}

#Preview {
    TVView()
        .environmentObject(AppModel.shared)
}
