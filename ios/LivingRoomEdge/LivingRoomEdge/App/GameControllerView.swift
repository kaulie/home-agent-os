import AVFoundation
import SwiftUI

/// iPhone game remote: voice + gesture → GameCommand (no Brain on realtime path).
struct GameControllerView: View {
    @StateObject private var session = GameSession.shared
    @StateObject private var bridge = GameInputBridge.shared
    @StateObject private var voice = GameVoiceController()
    @StateObject private var gesture = GameGestureController()
    @State private var armed = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    statusCard
                    previewCard
                    controls
                    hintBlock
                }
                .padding()
            }
            .background(EdgeTheme.ink.ignoresSafeArea())
            .navigationTitle("游戏遥控器")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear { wireHandlers() }
            .onReceive(NotificationCenter.default.publisher(for: .gameSessionActivated)) { _ in
                armed = true
                Task { await startInputs() }
            }
        }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(session.isActive ? "游戏已就绪" : "等待 game.launch")
                .font(.headline)
                .foregroundStyle(EdgeTheme.sand)
            if !session.gameURL.isEmpty {
                Text(session.gameURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Text("传输：\(bridge.transportLabel)")
                .font(.caption)
                .foregroundStyle(.secondary)
            if !session.lastCommandLabel.isEmpty {
                Text("最近：\(session.lastCommandLabel)")
                    .font(.caption.monospaced())
                    .foregroundStyle(EdgeTheme.sand.opacity(0.85))
            }
            if !bridge.lastError.isEmpty {
                Text(bridge.lastError).font(.caption).foregroundStyle(.red)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(EdgeTheme.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var previewCard: some View {
        Group {
            if let layer = gesture.previewLayer {
                CameraPreview(layer: layer)
                    .frame(height: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                RoundedRectangle(cornerRadius: 12)
                    .fill(EdgeTheme.panel)
                    .frame(height: 120)
                    .overlay(Text("摄像头预览").foregroundStyle(.secondary))
            }
        }
    }

    private var controls: some View {
        VStack(spacing: 12) {
            Button(armed ? "停止语音/手势" : "开始语音/手势") {
                Task {
                    if armed {
                        voice.stop()
                        gesture.stop()
                        armed = false
                    } else {
                        await startInputs()
                        armed = true
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(EdgeTheme.sand)

            HStack {
                cmdButton("开始", .start)
                cmdButton("暂停", .pause)
                cmdButton("继续", .resume)
            }
            HStack {
                cmdButton("←", .moveLeft)
                cmdButton("跳", .jump)
                cmdButton("→", .moveRight)
            }
        }
    }

    private var hintBlock: some View {
        Text("说：开始游戏 / 暂停 / 继续 / 向左 / 向右 / 跳\n挥臂或身体左右移动控制角色")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func cmdButton(_ label: String, _ type: GameCommandType) -> some View {
        Button(label) {
            Task {
                let cmd = GameCommand(type: type, source: .system)
                await bridge.send(cmd)
                session.noteCommand(type, source: .system)
            }
        }
        .buttonStyle(.bordered)
        .tint(EdgeTheme.sand)
    }

    private func wireHandlers() {
        voice.onCommand = { cmd in
            Task { await bridge.send(cmd) }
        }
        gesture.onCommand = { cmd in
            Task { await bridge.send(cmd) }
        }
    }

    private func startInputs() async {
        wireHandlers()
        if session.gameURL.isEmpty {
            bridge.configure(baseURL: TvGameLaunch.resolveGameURL(from: [:], brainURL: await AppModel.shared.intentServerURL))
        } else {
            bridge.configure(baseURL: session.gameURL)
        }
        await voice.start()
        await gesture.start()
    }
}

private struct CameraPreview: UIViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer

    func makeUIView(context: Context) -> UIView {
        let v = UIView()
        layer.frame = v.bounds
        v.layer.addSublayer(layer)
        return v
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        layer.frame = uiView.bounds
    }
}
