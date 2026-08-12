import Foundation

/// Façade for plugins to reach Edge runtime services (assets, …).
enum RuntimeAgentSDK {
    private static let lock = NSLock()
    private static var _edgeRuntimeContext = EdgeRuntimeContext()

    /// Shared Edge runtime context (injectable for tests).
    static var edgeRuntimeContext: EdgeRuntimeContext {
        get {
            lock.lock()
            defer { lock.unlock() }
            return _edgeRuntimeContext
        }
        set {
            lock.lock()
            _edgeRuntimeContext = newValue
            lock.unlock()
        }
    }

    /// Alias matching `getEdgeRuntimeContext()` call style.
    static func getEdgeRuntimeContext() -> EdgeRuntimeContext {
        edgeRuntimeContext
    }
}
