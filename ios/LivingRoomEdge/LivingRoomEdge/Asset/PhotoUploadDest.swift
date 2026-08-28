import Foundation

/// Shared photo dest endpoints. img-server is infrastructure, not a capability.
enum PhotoUploadDest {
    static let lanUpload = "http://192.168.3.73:8080/api/v1/photos/upload"
    static let lanPublic = "http://192.168.3.73:8080"
    static let cloudUpload = "http://115.190.153.53:9527/api/v1/photos/upload"
    static let cloudPublic = "http://115.190.153.53:8080"

    static func parse(_ params: [String: Any]) -> String {
        let raw = (
            (params["dest"] as? String)
                ?? (params["upload_dest"] as? String)
                ?? (params["uploadDest"] as? String)
                ?? "img_server"
        )
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
        if raw == "cloud" { return "cloud" }
        if raw == "gdrive" || raw == "google_drive" || raw == "googledrive" {
            return "gdrive"
        }
        if raw == "dropbox" { return "dropbox" }
        return "img_server"
    }

    static func displayName(_ dest: String) -> String {
        let d = dest.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if d == "lan" || d == "local" || d == "home" || d.isEmpty { return "img_server" }
        return d
    }

    /// dest for capability output: LAN Brain → img_server, Cloud Brain → cloud.
    static func wireDest(forIntentURL intentURL: String) -> String {
        let given = BrainEndpoint.displayBase(from: intentURL)
        let cloud = BrainEndpoint.displayBase(from: BrainEndpoint.cloudBaseURL)
        if hostsMatch(given, cloud) {
            return "cloud"
        }
        return "img_server"
    }

    /// Img-server endpoints for a dest. `dest=img_server` follows the **primary Brain**:
    /// cloud primary → cloud img-server, never LAN `192.168.3.73:8080`.
    static func endpoints(
        _ dest: String,
        primaryIntentURL: String? = nil
    ) throws -> (upload: String, publicBase: String, probe: String) {
        switch dest {
        case "gdrive":
            throw destError("dest=gdrive is not implemented yet (Google Drive is a plugin slot only)")
        case "dropbox":
            throw destError("dest=dropbox is not implemented yet (Dropbox is a plugin slot only)")
        default:
            break
        }
        let useCloud = dest == "cloud"
            || (primaryIntentURL.map { wireDest(forIntentURL: $0) == "cloud" } ?? false)
        if useCloud {
            return (cloudUpload, cloudPublic, "http://115.190.153.53:9527/")
        }
        return (lanUpload, lanPublic, "http://192.168.3.73:8080/health")
    }

    private static func hostsMatch(_ a: String, _ b: String) -> Bool {
        if a.compare(b, options: [.caseInsensitive, .diacriticInsensitive]) == .orderedSame {
            return true
        }
        let ha = URL(string: a)?.host?.lowercased() ?? ""
        let hb = URL(string: b)?.host?.lowercased() ?? ""
        return !ha.isEmpty && ha == hb
    }

    private static func destError(_ message: String) -> NSError {
        NSError(domain: "PhotoUploadDest", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
