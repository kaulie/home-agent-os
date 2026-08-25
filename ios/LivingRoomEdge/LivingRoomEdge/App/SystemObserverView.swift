import SwiftUI

/// Observer pane: system events + active sessions (API placeholders for now).
struct SystemObserverView: View {
    var body: some View {
        NavigationStack {
            ZStack {
                EdgeTheme.canvas
                ScrollView {
                    VStack(alignment: .leading, spacing: 28) {
                        VStack(alignment: .leading, spacing: 8) {
                            EdgeTheme.heroTitle("系统")
                            EdgeTheme.heroSubtitle("以 observer 身份旁观整屋动态。当前 Brain 尚未提供事件流 / 活跃 session 查询接口，先占位。")
                        }
                        .padding(.top, 8)

                        VStack(alignment: .leading, spacing: 12) {
                            EdgeTheme.sectionLabel("系统事件")
                            EdgeEmptyPlaceholder(
                                title: "事件流待接入",
                                detail: "预期展示：节点上线/下线、intent 入队与终态、能力调度失败等。待 Brain 提供 observer 事件 API 后填充。"
                            )
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            EdgeTheme.sectionLabel("活跃 Session")
                            EdgeEmptyPlaceholder(
                                title: "Session 列表待接入",
                                detail: "预期展示：当前进行中的 intent / 对话 session 及其参与节点。待 Brain 提供活跃 session 查询后填充。"
                            )
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 36)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("系统")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                }
            }
            .toolbarBackground(EdgeTheme.ink, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }
}
