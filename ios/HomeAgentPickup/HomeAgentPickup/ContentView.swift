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

                VStack(spacing: 24) {
                    connectionPill
                        .padding(.top, 8)

                    if let error = model.prominentErrorMessage {
                        ErrorBannerView(message: error, showSettingsLink: !model.micPermissionGranted)
                    }

                    Spacer()

                    micButton
                    statusBlock

                    if model.userListeningEnabled {
                        AudioLevelBars(level: model.audioLevel)
                            .padding(.horizontal, 40)
                        hearingBadge
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
            .navigationTitle("Home Mic")
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
                Task { await model.refreshPermissions() }
            }
            .onChange(of: model.userListeningEnabled) { enabled in
                pulse = enabled
            }
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
                Task { await model.refreshPermissions() }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var connectionPill: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(model.isConnected ? Color.green : Color.orange)
                .frame(width: 10, height: 10)
            Text(model.isConnected ? "已就绪" : model.userConnectionStatus)
                .font(.footnote.weight(.medium))
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
                } else {
                    Circle()
                        .stroke(Color.white.opacity(0.12), lineWidth: 2)
                        .frame(width: 190, height: 190)
                }

                Circle()
                    .fill(
                        model.userListeningEnabled
                            ? LinearGradient(colors: [.red, Color(red: 0.85, green: 0.15, blue: 0.2)], startPoint: .topLeading, endPoint: .bottomTrailing)
                            : LinearGradient(colors: [Color(white: 0.32), Color(white: 0.18)], startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .frame(width: 160, height: 160)
                    .shadow(color: model.userListeningEnabled ? .red.opacity(0.45) : .clear, radius: 24)

                Image(systemName: "mic.fill")
                    .font(.system(size: 64, weight: .medium))
                    .foregroundStyle(.white.opacity(model.userListeningEnabled ? 1 : 0.85))
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(model.userListeningEnabled ? "关闭拾音" : "开始拾音")
    }

    private var statusBlock: some View {
        Text(model.statusHeadline)
            .font(.system(size: 40, weight: .bold, design: .rounded))
            .foregroundStyle(model.userListeningEnabled ? Color.red : Color(white: 0.75))
    }

    private var hearingBadge: some View {
        Text(model.userCaptureStatus)
            .font(.headline.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 8)
            .background(
                model.audioLevel > 0.06 ? Color.green.opacity(0.85) : Color.red.opacity(0.85),
                in: Capsule()
            )
            .animation(.easeInOut(duration: 0.2), value: model.audioLevel > 0.06)
    }
}

private struct ErrorBannerView: View {
    let message: String
    let showSettingsLink: Bool

    var body: some View {
        VStack(spacing: 12) {
            Text(message)
                .font(.title3.weight(.bold))
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
            if showSettingsLink {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    Link("去系统设置开启", destination: url)
                        .font(.headline)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity)
        .background(Color.orange.opacity(0.22), in: RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.orange.opacity(0.45), lineWidth: 1)
        )
        .padding(.horizontal, 20)
    }
}

private struct AudioLevelBars: View {
    let level: Float
    private let barCount = 24

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: false)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            Canvas { context, size in
                let spacing: CGFloat = 3
                let totalSpacing = spacing * CGFloat(barCount - 1)
                let barWidth = max(2, (size.width - totalSpacing) / CGFloat(barCount))
                let midY = size.height / 2
                // Boost quiet speech into visible motion; floor so idle isn't a black slab.
                let boosted = max(0.08, min(1, pow(Double(max(level, 0)), 0.55) * 1.35))

                for index in 0 ..< barCount {
                    let phase = Double(index) * 0.55 + t * 6.5
                    let idleWave = (sin(phase) * 0.5 + 0.5) * 0.22
                    let voiceWave = sin(phase * 1.3 + Double(level) * 10) * 0.18 * boosted
                    let heightFactor = min(1, idleWave + boosted * 0.85 + voiceWave)
                    let barHeight = max(6, size.height * heightFactor)
                    let x = CGFloat(index) * (barWidth + spacing)
                    let rect = CGRect(
                        x: x,
                        y: midY - barHeight / 2,
                        width: barWidth,
                        height: barHeight
                    )
                    let path = Path(roundedRect: rect, cornerRadius: barWidth / 2)
                    context.fill(path, with: .color(barColor(heightFactor: heightFactor, index: index)))
                }
            }
            .frame(height: 72)
            .padding(.horizontal, 8)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.white.opacity(0.08))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.white.opacity(0.18), lineWidth: 1)
            )
        }
        .accessibilityLabel("音量 \(Int(level * 100))%")
    }

    private func barColor(heightFactor: Double, index: Int) -> Color {
        if heightFactor < 0.28 {
            return Color.cyan.opacity(0.55)
        }
        let ratio = Double(index) / Double(max(barCount - 1, 1))
        if ratio > 0.78 {
            return Color.red.opacity(0.95)
        }
        if ratio > 0.55 {
            return Color.orange.opacity(0.95)
        }
        return Color.green.opacity(0.95)
    }
}

private struct PowerSaveView: View {
    var body: some View {
        Color.black
            .ignoresSafeArea()
    }
}
