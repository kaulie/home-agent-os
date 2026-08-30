import SwiftUI

/// 直播 Hub：顶部分段「自己直播 / 观看」。
/// - 第一段原样嵌入推流工作台 `LiveStreamWorkspaceView`（行为不变）
/// - 第二段为 LAN 观看列表 `LiveWatchListView`（轮询 status + HLS 播放）
struct LiveStreamHubView: View {
    @Binding var showSettings: Bool
    @Binding var settingsFocus: SettingsFocus
    var onClose: () -> Void

    private enum LiveSegment: String, CaseIterable, Identifiable {
        case publish
        case watch

        var id: String { rawValue }

        var label: String {
            switch self {
            case .publish: return "自己直播"
            case .watch: return "观看"
            }
        }
    }

    @State private var segment: LiveSegment = .publish

    var body: some View {
        ZStack(alignment: .topLeading) {
            EdgeTheme.canvas.ignoresSafeArea()
            VStack(spacing: 0) {
                segmentPicker
                content
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
    }

    private var segmentPicker: some View {
        Picker("直播", selection: $segment) {
            ForEach(LiveSegment.allCases) { seg in
                Text(seg.label).tag(seg)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, 24)
        .padding(.top, 6)
        .padding(.bottom, 8)
        .tint(EdgeTheme.sand)
        .accessibilityLabel("直播分段：自己直播或观看")
    }

    @ViewBuilder
    private var content: some View {
        switch segment {
        case .publish:
            LiveStreamWorkspaceView(showSettings: $showSettings, settingsFocus: $settingsFocus) {
                onClose()
            }
        case .watch:
            LiveWatchListView(showSettings: $showSettings, settingsFocus: $settingsFocus)
        }
    }
}
