import Foundation

/// Base abstraction for device controllers (GoPro, speakers, displays, …).
protocol DeviceController: AnyObject {
    var controllerId: String { get }
    var displayName: String { get }
}

/// Uniform result returned by controller capability methods.
struct ControllerResult {
    let ok: Bool
    let message: String
    let data: Data?
    /// Structured capability outputs (e.g. photo_url) when available.
    let outputs: [String: String]?

    static func success(
        _ message: String,
        data: Data? = nil,
        outputs: [String: String]? = nil
    ) -> ControllerResult {
        ControllerResult(ok: true, message: message, data: data, outputs: outputs)
    }

    static func failure(_ message: String) -> ControllerResult {
        ControllerResult(ok: false, message: message, data: nil, outputs: nil)
    }
}
