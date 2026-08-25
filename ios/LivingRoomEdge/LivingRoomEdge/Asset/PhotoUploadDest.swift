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

    static func endpoints(_ dest: String) throws -> (upload: String, publicBase: String, probe: String) {
        switch dest {
        case "cloud":
            return (cloudUpload, cloudPublic, "http://115.190.153.53:9527/")
        case "gdrive":
            throw destError("dest=gdrive is not implemented yet (Google Drive is a plugin slot only)")
        case "dropbox":
            throw destError("dest=dropbox is not implemented yet (Dropbox is a plugin slot only)")
        default:
            return (lanUpload, lanPublic, "http://192.168.3.73:8080/health")
        }
    }

    private static func destError(_ message: String) -> NSError {
        NSError(domain: "PhotoUploadDest", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
