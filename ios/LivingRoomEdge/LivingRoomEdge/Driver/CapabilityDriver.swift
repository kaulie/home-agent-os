import Foundation

/// Lightweight, extensible driver surface (identity / network join / self-status / capability ids).
/// Device-specific APIs (e.g. GoPro shutter) stay on concrete drivers — not on this protocol.
protocol CapabilityDriver: AnyObject {
    func identity() async -> DriverIdentity
    func connect() async throws
    func disconnect() async throws
    func status() async -> DriverStatus
    func capabilities() async -> [String]
}

struct DriverIdentity: Equatable {
    let driverId: String
    let displayName: String
    let endpoint: String?
}

struct DriverStatus: Equatable {
    let connected: Bool
    let summary: String
}
