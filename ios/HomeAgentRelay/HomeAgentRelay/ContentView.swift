import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var server: RelayServer
    @State private var startPressedLabel = false
    @State private var stopPressedLabel = false
    @State private var actionHint = ""

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    controls
                    httpSection
                    webSocketSection
                    addressSection
                    teslaSection
                    connectionsSection
                    lastMessageSection
                    diagnosticsSection
                    logSection
                }
                .padding()
            }
            .navigationTitle("Home Agent Relay")
            .navigationBarTitleDisplayMode(.inline)
        }
        .navigationViewStyle(.stack)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Home Agent Relay")
                .font(.title.bold())
            Text("Personal Hotspot TCP/HTTP relay for Tesla")
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
    }

    private var httpSection: some View {
        GroupBox("HTTP Server") {
            VStack(alignment: .leading, spacing: 6) {
                labeled("Status", server.httpStatus)
                labeled("HTTP Port", "\(RelayServer.httpPort)")
                labeled("NWListener state", server.httpListenerState)
                if let error = server.httpLastError {
                    labeled("NWListener error", error)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var webSocketSection: some View {
        GroupBox("WebSocket Server") {
            VStack(alignment: .leading, spacing: 6) {
                labeled("Status", server.webSocketStatus)
                labeled("WebSocket Port", "\(RelayServer.webSocketPort)")
                labeled("NWListener state", server.webSocketListenerState)
                if let error = server.webSocketLastError {
                    labeled("NWListener error", error)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var addressSection: some View {
        GroupBox("Local Addresses") {
            VStack(alignment: .leading, spacing: 6) {
                if server.addresses.isEmpty {
                    Text("No IPv4 addresses yet")
                        .foregroundColor(.secondary)
                } else {
                    ForEach(server.addresses) { item in
                        HStack {
                            Text(item.address)
                                .font(.body.monospaced())
                            Spacer()
                            Text(item.interface)
                                .font(.caption.monospaced())
                                .foregroundColor(.secondary)
                        }
                    }
                }
                Text(server.hotspotHint)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.top, 4)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
        }
    }

    private var teslaSection: some View {
        GroupBox("Open this URL on Tesla:") {
            VStack(alignment: .leading, spacing: 8) {
                if server.teslaURLs.isEmpty {
                    Text("http://<detected-ip>:8080/receiver")
                        .font(.body.monospaced())
                        .foregroundColor(.secondary)
                } else {
                    ForEach(server.teslaURLs, id: \.self) { url in
                        Text(url)
                            .font(.body.monospaced().bold())
                            .textSelection(.enabled)
                    }
                }
                Text("WebSocket (phase 2)")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.top, 4)
                ForEach(server.webSocketURLs, id: \.self) { url in
                    Text(url)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var connectionsSection: some View {
        GroupBox("Connections") {
            VStack(alignment: .leading, spacing: 10) {
                if server.peerGroups.isEmpty {
                    Text("No client has connected yet")
                        .foregroundColor(.secondary)
                } else {
                    Text("\(server.peerGroups.count) IP · \(server.peerConnections.filter(\.isActive).count) live")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(server.peerGroups) { group in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(group.ip)
                                    .font(.title3.monospaced().bold())
                                    .textSelection(.enabled)
                                Spacer()
                                if group.activeCount > 0 {
                                    Text("LIVE")
                                        .font(.caption.bold())
                                        .foregroundColor(.green)
                                }
                            }
                            if let ua = group.userAgent {
                                Text(ua)
                                    .font(.caption.monospaced())
                                    .foregroundColor(.secondary)
                                    .textSelection(.enabled)
                            }
                            ForEach(group.connections) { conn in
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(alignment: .firstTextBaseline) {
                                        Text(conn.kind)
                                            .font(.caption.bold())
                                            .frame(width: 72, alignment: .leading)
                                        Text(conn.detail)
                                            .font(.caption.monospaced())
                                        Spacer()
                                        Text(conn.isActive ? "connected" : "closed")
                                            .font(.caption)
                                            .foregroundColor(conn.isActive ? .green : .secondary)
                                        Text(RelayLog.timeFormatter.string(from: conn.lastActivityAt))
                                            .font(.caption.monospaced())
                                            .foregroundColor(.secondary)
                                    }
                                    if let ua = conn.userAgent {
                                        Text("UA: \(ua)")
                                            .font(.caption.monospaced())
                                            .foregroundColor(.primary)
                                            .textSelection(.enabled)
                                    }
                                    ForEach(conn.headers.filter { $0.name.lowercased() != "user-agent" }) { header in
                                        HStack(alignment: .top, spacing: 6) {
                                            Text(header.name)
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                                .frame(width: 110, alignment: .leading)
                                            Text(header.value)
                                                .font(.caption2.monospaced())
                                                .textSelection(.enabled)
                                        }
                                    }
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var lastMessageSection: some View {
        GroupBox("Last WebSocket message") {
            Text(server.lastWebSocketMessage.isEmpty ? "(none yet)" : server.lastWebSocketMessage)
                .font(.caption.monospaced())
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
        }
    }

    private var controls: some View {
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                Button {
                    bump("Start Server — tapped", flashing: $startPressedLabel)
                    server.start()
                } label: {
                    Text(server.isServerActive ? "Running" : "Start Server")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RelayPressButtonStyle(
                    fill: .green,
                    enabled: !server.isServerActive,
                    isFlashing: startPressedLabel
                ))
                .disabled(server.isServerActive)

                Button {
                    bump("Stop Server — tapped", flashing: $stopPressedLabel)
                    server.stop()
                } label: {
                    Text(server.isServerActive ? "Stop Server" : "Stopped")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(RelayPressButtonStyle(
                    fill: .red,
                    enabled: server.isServerActive,
                    isFlashing: stopPressedLabel
                ))
                .disabled(!server.isServerActive)
            }

            if !actionHint.isEmpty {
                Text(actionHint)
                    .font(.subheadline.bold())
                    .foregroundColor(.primary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .background(Color.yellow.opacity(0.35))
                    .cornerRadius(8)
            }

            Button("Dump Diagnostics") {
                bump("Dump Diagnostics — tapped", flashing: nil)
                server.dumpDiagnostics()
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.bordered)
        }
    }

    private func bump(_ hint: String, flashing: Binding<Bool>?) {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        actionHint = hint
        flashing?.wrappedValue = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            flashing?.wrappedValue = false
            if actionHint == hint {
                actionHint = ""
            }
        }
    }

    private var diagnosticsSection: some View {
        GroupBox("If Tesla cannot connect") {
            Text("Keep this app in the foreground. Dump diagnostics, then check IPv4, NWListener state/error, connection attempts, and whether a Personal Hotspot 172.20.10.x address is present. Do not assume a code bug until those fields are collected.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }

    private var logSection: some View {
        GroupBox("Connection log") {
            VStack(alignment: .leading, spacing: 4) {
                if server.logs.isEmpty {
                    Text("No log yet")
                        .foregroundColor(.secondary)
                } else {
                    ForEach(Array(server.logs.reversed())) { entry in
                        Text(entry.line)
                            .font(.caption.monospaced())
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
        }
    }

    private func labeled(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text("\(title):")
                .foregroundColor(.secondary)
            Text(value)
                .font(.body.monospaced())
        }
    }
}

private struct RelayPressButtonStyle: ButtonStyle {
    var fill: Color
    var enabled: Bool
    var isFlashing: Bool

    func makeBody(configuration: Configuration) -> some View {
        let pressed = enabled && (isFlashing || configuration.isPressed)
        configuration.label
            .font(.headline)
            .foregroundColor(.white.opacity(enabled ? 1 : 0.7))
            .padding(.vertical, 16)
            .background(fill.opacity(enabled ? (pressed ? 0.55 : 1) : 0.28))
            .cornerRadius(12)
            .scaleEffect(pressed ? 0.94 : 1)
            .shadow(color: fill.opacity(enabled && !pressed ? 0.35 : 0), radius: 4, y: 2)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
            .animation(.easeOut(duration: 0.12), value: isFlashing)
            .animation(.easeOut(duration: 0.12), value: enabled)
    }
}

#Preview {
    ContentView()
        .environmentObject(RelayServer.shared)
}
