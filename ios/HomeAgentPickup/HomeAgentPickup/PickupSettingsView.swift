import SwiftUI

struct PickupSettingsView: View {
    @EnvironmentObject private var model: PickupViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var showFeedback = false
    @State private var showAdvanced = false
    @State private var pickupHost = PickupSettings.serverHost
    @State private var pickupPort = String(PickupSettings.serverPort)
    @State private var brainURL = PickupSettings.brainIntentURL
    @State private var feedbackParticipantId = PickupSettings.feedbackParticipantId
    @State private var energyGateEnabled = PickupSettings.energyGateEnabled

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

                Section("Mac 拾音地址") {
                    TextField("Mac 主机", text: $pickupHost)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("端口（voice.stream ingest）", text: $pickupPort)
                        .keyboardType(.numberPad)
                    Text("音频直连客厅 Mac（默认 192.168.3.84:8792），由 Mac 切句 / STT 后再到 Brain Intent。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("发送初筛") {
                    Toggle("静音不上传（能量门）", isOn: $energyGateEnabled)
                    Text("开口才发 PCM，带约 120ms 前摇与 800ms 挂起，避免字头被砍、句中短停不断流。关闭则恢复持续推流。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section {
                    DisclosureGroup("高级与调试", isExpanded: $showAdvanced) {
                        LabeledContent("当前目标", value: model.serverLabel)
                        LabeledContent("TCP", value: model.connectionLabel)
                        LabeledContent("心跳", value: "\(model.heartbeatCount)")
                        LabeledContent("采集", value: model.captureLabel)
                        LabeledContent("已发送 PCM", value: model.pcmSentLabel)
                        LabeledContent("模式", value: model.modeLabel)
                        LabeledContent("设备 ID", value: PickupSettings.deviceId)

                        TextField("Brain Intent URL（仅反馈等）", text: $brainURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        TextField("Edge participant_id（LivingRoomEdge 心跳登记的 id）", text: $feedbackParticipantId)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        Text("HAP1 hello 会带上此 id 作为 Input Source；空则暂用设备 ID。与 LivingRoomEdge 同机时应填那边登记的 participant_id。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)

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
            .onChange(of: pickupHost) { value in
                PickupSettings.serverHost = value.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .onChange(of: pickupPort) { value in
                if let port = UInt16(value.trimmingCharacters(in: .whitespacesAndNewlines)), port > 0 {
                    PickupSettings.serverPort = port
                }
            }
            .onChange(of: brainURL) { value in
                PickupSettings.brainIntentURL = value
            }
            .onChange(of: feedbackParticipantId) { value in
                PickupSettings.feedbackParticipantId = value
            }
            .onChange(of: energyGateEnabled) { value in
                PickupSettings.energyGateEnabled = value
            }
        }
    }
}
