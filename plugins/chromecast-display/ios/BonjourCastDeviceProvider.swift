import Foundation
import GoogleCast
import Network

/// Factory for synthesizing `GCKDevice` from Bonjour / known IP.
///
/// Important: devices must use `kGCKCastDeviceCategory` so `GCKSessionManager`
/// routes session creation through the **built-in** Cast provider. A custom
/// registered category that returns `GCKCastSession` often hangs at
/// "start session timed out" because the SDK treats it as a non-Cast device type.
final class CastDeviceFactory: GCKDeviceProvider {
    static let shared = CastDeviceFactory()

    /// Last-resort host when Bonjour names are visible but DNS-SD resolve fails.
    static let fallbackHostDefaultsKey = "chromecast.display.fallbackHost"
    static let defaultFallbackHost = "192.168.3.59"
    static let castPort: UInt16 = 8009

    private init() {
        super.init(deviceCategory: kGCKCastDeviceCategory)
    }

    override func startDiscovery() {
        // Unregistered factory — discovery is handled by Cast SDK + Bonjour helper.
        notifyDidStartDiscovery()
    }

    override func stopDiscovery() {}

    override func createSession(
        for device: GCKDevice,
        sessionID: String?,
        sessionOptions: [String: any NSCoding & NSObjectProtocol]?
    ) -> GCKSession {
        // Should not be called (factory is not registered). Keep a safe stub.
        assertionFailure("CastDeviceFactory must not be registered as a device provider")
        let options = GCKCastOptions(discoveryCriteria: GCKDiscoveryCriteria(
            applicationID: kGCKDefaultMediaReceiverApplicationID
        ))
        return GCKCastSession(
            device: device,
            sessionID: sessionID,
            sessionOptions: sessionOptions,
            castOptions: options
        )
    }

    /// Build a Cast-category device the built-in provider can connect to.
    func makeDevice(deviceID: String, host: String, port: UInt16 = castPort, friendlyName: String?) -> GCKDevice {
        let id = deviceID.isEmpty ? (friendlyName ?? host) : deviceID
        let address = GCKNetworkAddress(type: .iPv4, ipAddress: host)
        // Always use Cast control port; Bonjour TCP probe ports can be misleading.
        let device = createDevice(withID: id, networkAddress: address, servicePort: Self.castPort)
        device.friendlyName = friendlyName ?? "Chromecast"
        device.modelName = "Chromecast"
        UserDefaults.standard.set(host, forKey: Self.fallbackHostDefaultsKey)
        NSLog(
            "%@",
            "[CastDeviceFactory] makeDevice id=\(id) \(host):\(Self.castPort) "
                + "category=\(device.category) name=\(device.friendlyName ?? "")"
        )
        return device
    }

    /// Prefer resolved Bonjour hosts; else fallback IP when instance names were seen.
    func makeDevicesFromBonjour() -> [GCKDevice] {
        var devices: [GCKDevice] = []
        var seenIDs = Set<String>()

        for seen in LocalNetworkAccessTrigger.shared.seenDevices {
            let id = seen.deviceID
            if seenIDs.contains(id) { continue }
            seenIDs.insert(id)
            devices.append(makeDevice(
                deviceID: id,
                host: seen.host,
                port: Self.castPort,
                friendlyName: seen.name
            ))
        }

        let fallback = UserDefaults.standard.string(forKey: Self.fallbackHostDefaultsKey)
            ?? Self.defaultFallbackHost
        for name in LocalNetworkAccessTrigger.shared.seenInstanceNames {
            let id = Self.deviceID(fromBonjourName: name)
            if seenIDs.contains(id) { continue }
            if let host = LocalNetworkAccessTrigger.shared.resolvedHost(forInstanceName: name) {
                seenIDs.insert(id)
                devices.append(makeDevice(deviceID: id, host: host, friendlyName: name))
            } else {
                // Kick async resolve for next attempt; still offer fallback device now.
                LocalNetworkAccessTrigger.shared.resolveInstance(name: name) { _, _ in }
                seenIDs.insert(id)
                NSLog("%@", "[CastDeviceFactory] no IP yet for \(name); using fallback \(fallback)")
                devices.append(makeDevice(deviceID: id, host: fallback, friendlyName: name))
            }
        }

        if devices.isEmpty {
            // Last resort: known Chromecast on LAN (user's living-room unit).
            let id = "fallback-\(fallback.replacingOccurrences(of: ".", with: "-"))"
            devices.append(makeDevice(
                deviceID: id,
                host: fallback,
                friendlyName: "Chromecast (\(fallback))"
            ))
        }
        return devices
    }

    static func deviceID(fromBonjourName name: String) -> String {
        let prefix = "Chromecast-"
        if name.hasPrefix(prefix) {
            return String(name.dropFirst(prefix.count))
        }
        return name
    }
}

// Backward-compatible name used by older call sites / docs.
typealias BonjourCastDeviceProvider = CastDeviceFactory
