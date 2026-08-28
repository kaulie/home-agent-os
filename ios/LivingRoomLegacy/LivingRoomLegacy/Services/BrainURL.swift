import Foundation

enum BrainURL {
    static func normalizeIntentURL(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        if value.isEmpty {
            return ParticipantStore.defaultBrainIntentURL
        }
        if value.hasSuffix("/api/v1/intent") {
            return value
        }
        if value.contains("/api/v1/") {
            return value
        }
        return value + "/api/v1/intent"
    }

    static func displayBase(from intentURL: String) -> String {
        var value = normalizeIntentURL(intentURL)
        if value.hasSuffix("/api/v1/intent") {
            value = String(value.dropLast("/api/v1/intent".count))
        }
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }

    static func apiURL(fromIntentURL intentURL: String, leaf: String) -> URL? {
        let trimmed = normalizeIntentURL(intentURL)
        guard var components = URLComponents(string: trimmed) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + leaf
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + leaf
        } else {
            path = "/api/v1/" + leaf
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func intentDetailURL(fromIntentURL intentURL: String, intentId: String) -> URL? {
        guard var components = URLComponents(string: normalizeIntentURL(intentURL)) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intent_detail"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intent_detail"
        } else {
            path = "/api/v1/intent_detail"
        }
        components.path = path
        components.queryItems = [URLQueryItem(name: "intent_id", value: intentId)]
        return components.url
    }

    static func assetsUploadURL(fromIntentURL intentURL: String) -> URL? {
        apiURL(fromIntentURL: intentURL, leaf: "assets/upload")
    }

    static func debugReportURL(fromIntentURL intentURL: String) -> URL? {
        apiURL(fromIntentURL: intentURL, leaf: "debug/report")
    }
}
