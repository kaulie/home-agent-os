import Foundation

struct DevDocEntry: Identifiable, Codable, Hashable {
    let path: String
    let title: String
    let size: Int

    var id: String { path }
}

struct DevDocContent: Codable, Hashable {
    let path: String
    let title: String
    let content: String
    let size: Int
}

struct DevDocsIndexResponse: Codable {
    let ok: Bool?
    let docs: [DevDocEntry]?
    let count: Int?
    let root: String?
    let error: String?
}

struct DevDocContentResponse: Codable {
    let ok: Bool?
    let doc: DevDocContent?
    let error: String?
}
