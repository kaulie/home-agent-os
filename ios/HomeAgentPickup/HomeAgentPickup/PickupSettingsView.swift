import SwiftUI

struct PickupSettingsView: View {
    @EnvironmentObject private var model: PickupViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var showFeedback = false
    @State private var showAdvanced = false
    @State private var brainURL = PickupSettings.brainIntentURL
    @State private var feedbackParticipantId = PickupSettings.feedbackParticipantId
    @State private var defaultIntentId = PickupSettings.defaultFeedbackIntentId

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button {
                        showFeedback = true
                    } label: {
                        Label("遇到问题？提交反馈", systemImage: "exclamationmark.bubble")
                    }
                }

                Section("当前状态") {
                    LabeledContent("网络", value: model.userConnectionStatus)
                    LabeledContent("拾音", value: model.userCaptureStatus)
                }

                Section {
                    DisclosureGroup("高级与调试", isExpanded: $showAdvanced) {
                        LabeledContent("服务端", value: model.serverLabel)
                        LabeledContent("TCP", value: model.connectionLabel)
                        LabeledContent("心跳", value: "\(model.heartbeatCount)")
                        LabeledContent("采集", value: model.captureLabel)
                        LabeledContent("已发送 PCM", value: model.pcmSentLabel)
                        LabeledContent("模式", value: model.modeLabel)

                        TextField("Brain Intent URL", text: $brainURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        TextField("participant_id", text: $feedbackParticipantId)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("默认 Intent #", text: $defaultIntentId)
                            .keyboardType(.numberPad)

                        Text("引导式访问锁定本 App，并保持前台与外接电源。锁屏会中断录音。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
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
