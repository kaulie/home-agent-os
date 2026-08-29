import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: PickupViewModel

    var body: some View {
        Group {
            if model.powerSaveActive {
                PowerSaveView()
            } else {
                NormalStatusView()
            }
        }
        .animation(.easeInOut(duration: 0.25), value: model.powerSaveActive)
    }
}

private struct NormalStatusView: View {
    @EnvironmentObject private var model: PickupViewModel
    @State private var showFeedback = false
    @State private var brainURL = PickupSettings.brainIntentURL
    @State private var feedbackParticipantId = PickupSettings.feedbackParticipantId
    @State private var defaultIntentId = PickupSettings.defaultFeedbackIntentId

    var body: some View {
        NavigationStack {
            Form {
                Section("连接") {
                    LabeledContent("服务端", value: model.serverLabel)
                    LabeledContent("TCP", value: model.connectionLabel)
                    LabeledContent("心跳", value: "\(model.heartbeatCount)")
                }
                Section("采集") {
                    LabeledContent("麦克风", value: model.captureLabel)
                    LabeledContent("已发送 PCM", value: model.pcmSentLabel)
                    LabeledContent("模式", value: model.modeLabel)
                }
                if !model.lastError.isEmpty {
                    Section("提示") {
                        Text(model.lastError).foregroundStyle(.red).font(.footnote)
                    }
                }
                Section("反馈配置") {
                    TextField("Brain Intent URL", text: $brainURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("participant_id（Intent 发出端）", text: $feedbackParticipantId)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("默认 Intent #（可选）", text: $defaultIntentId)
                        .keyboardType(.numberPad)
                    Text("反馈走 Brain /api/v1/debug/report；participant_id 须与该 Intent 的发出端一致。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section {
                    Button {
                        showFeedback = true
                    } label: {
                        Label("提交问题反馈", systemImage: "exclamationmark.bubble")
                    }
                }
                Section("部署说明") {
                    Text("请开启系统「引导式访问」锁定本 App，并保持前台与外接电源。锁屏会中断录音。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("拾音终端")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("反馈") { showFeedback = true }
                }
            }
            .sheet(isPresented: $showFeedback) {
                FeedbackSheetView()
                    .environmentObject(model)
            }
            .onChange(of: brainURL) { value in
                PickupSettings.brainIntentURL = value
            }
            .onChange(of: feedbackParticipantId) { value in
                PickupSettings.feedbackParticipantId = value
            }
            .onChange(of: defaultIntentId) { value in
                PickupSettings.defaultFeedbackIntentId = value
            }
        }
    }
}

private struct PowerSaveView: View {
    var body: some View {
        Color.black
            .ignoresSafeArea()
    }
}
