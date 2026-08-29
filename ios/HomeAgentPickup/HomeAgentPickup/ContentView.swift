import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: PickupViewModel

    var body: some View {
        Group {
            if model.powerSaveActive {
                PowerSaveView()
            } else {
                MicMainView()
            }
        }
        .animation(.easeInOut(duration: 0.25), value: model.powerSaveActive)
    }
}

private struct MicMainView: View {
    @EnvironmentObject private var model: PickupViewModel
    @State private var showSettings = false
    @State private var pulse = false

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: model.userListeningEnabled
                        ? [Color(red: 0.12, green: 0.04, blue: 0.06), Color.black]
                        : [Color(red: 0.08, green: 0.09, blue: 0.12), Color.black],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                VStack(spacing: 28) {
                    connectionPill
                        .padding(.top, 8)

                    Spacer()

                    if let error = model.prominentErrorMessage {
                        ProminentErrorView(message: error)
                    } else {
                        micButton
                        statusBlock
                        if model.userListeningEnabled {
                            AudioLevelBars(level: model.audioLevel)
                                .padding(.horizontal, 40)
                            liveBadge
                        }
                    }

                    Spacer()

                    Text(model.statusHint)
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                        .padding(.bottom, 24)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .font(.title3)
                    }
                    .accessibilityLabel("设置")
                }
            }
            .sheet(isPresented: $showSettings) {
                PickupSettingsView()
                    .environmentObject(model)
            }
            .onAppear {
                pulse = model.userListeningEnabled
            }
            .onChange(of: model.userListeningEnabled) { enabled in
                pulse = enabled
            }
        }
        .preferredColorScheme(.dark)
    }

    private var connectionPill: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(model.isConnected ? Color.green : Color.orange)
                .frame(width: 10, height: 10)
            Text(model.isConnected ? "已连接 \(model.serverLabel)" : model.connectionLabel)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial, in: Capsule())
    }

    private var micButton: some View {
        Button {
            model.toggleListening()
        } label: {
            ZStack {
                if model.userListeningEnabled {
                    Circle()
                        .stroke(Color.red.opacity(0.35), lineWidth: 3)
                        .frame(width: 220, height: 220)
                        .scaleEffect(pulse ? 1.08 : 0.94)
                        .opacity(pulse ? 0.35 : 0.75)
                        .animation(
                            .easeInOut(duration: 1.1).repeatForever(autoreverses: true),
                            value: pulse
                        )
                    Circle()
                        .stroke(Color.red.opacity(0.55), lineWidth: 2)
                        .frame(width: 190, height: 190)
                }

                Circle()
                    .fill(
                        model.userListeningEnabled
                            ? LinearGradient(colors: [.red, Color(red: 0.85, green: 0.15, blue: 0.2)], startPoint: .topLeading, endPoint: .bottomTrailing)
                            : LinearGradient(colors: [Color(white: 0.28), Color(white: 0.16)], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .frame(width: 160, height: 160)
                    .shadow(color: model.userListeningEnabled ? .red.opacity(0.45) : .clear, radius: 24)

                Image(systemName: model.userListeningEnabled ? "mic.fill" : "mic.slash.fill")
                    .font(.system(size: 64, weight: .medium))
                    .foregroundStyle(.white)
            }
        }
        .buttonStyle(.plain)
        .disabled(!model.micPermissionGranted)
        .accessibilityLabel(model.userListeningEnabled ? "关闭拾音" : "开始拾音")
    }

    private var statusBlock: some View {
        VStack(spacing: 8) {
            Text(model.statusHeadline)
                .font(.system(size: 40, weight: .bold, design: .rounded))
                .foregroundStyle(model.userListeningEnabled ? Color.red : Color(white: 0.75))
            if model.userListeningEnabled, model.isConnected {
                Text("LIVE")
                    .font(.caption.weight(.heavy))
                    .tracking(3)
                    .foregroundStyle(.red.opacity(0.85))
            }
        }
    }

    private var liveBadge: some View {
        Text("正在听")
            .font(.headline.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 8)
            .background(Color.red.opacity(0.85), in: Capsule())
    }
}

private struct ProminentErrorView: View {
    let message: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.orange)
            Text(message)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
                .padding(.horizontal, 20)
        }
        .padding(.vertical, 32)
    }
}

private struct AudioLevelBars: View {
    let level: Float
    private let barCount = 12

    var body: some View {
        HStack(alignment: .bottom, spacing: 6) {
            ForEach(0 ..< barCount, id: \.self) { index in
                RoundedRectangle(cornerRadius: 3)
                    .fill(barColor(for: index))
                    .frame(width: 10, height: barHeight(for: index))
            }
        }
        .frame(height: 56)
        .animation(.easeOut(duration: 0.08), value: level)
    }

    private func barHeight(for index: Int) -> CGFloat {
        let threshold = Float(index + 1) / Float(barCount)
        let active = level >= threshold * 0.65
        let base: CGFloat = active ? 12 + CGFloat(level) * 44 : 8
        let wave = sin(Double(index) * 0.7 + Double(level) * 8) * 4
        return min(56, base + CGFloat(wave))
    }

    private func barColor(for index: Int) -> Color {
        let threshold = Float(index + 1) / Float(barCount)
        if level < threshold * 0.5 { return Color.white.opacity(0.18) }
        if index >= barCount - 3 { return .red }
        if index >= barCount - 6 { return .orange }
        return .green
    }
}

private struct PowerSaveView: View {
    var body: some View {
        Color.black
            .ignoresSafeArea()
    }
}
