import UIKit

enum ReadingPhotoUploadState: String, Codable {
    case none
    case uploading
    case uploaded
    case failed
}

struct ReadingPhotoRecord: Codable {
    let id: String
    let createdAt: TimeInterval
    var uploadState: ReadingPhotoUploadState
    var assetId: String?
}

enum ReadingPhotoStore {
    private static let indexKey = "legacy.reading.photos.index"
    private static var photosDir: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("reading_photos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func recent(limit: Int = 20) -> [ReadingPhotoRecord] {
        loadIndex().sorted { $0.createdAt > $1.createdAt }.prefix(limit).map { $0 }
    }

    static func fileURL(for id: String) -> URL {
        photosDir.appendingPathComponent("\(id).jpg")
    }

    @discardableResult
    static func save(jpeg: Data) -> ReadingPhotoRecord {
        let id = UUID().uuidString
        let url = fileURL(for: id)
        try? jpeg.write(to: url)
        var record = ReadingPhotoRecord(
            id: id,
            createdAt: Date().timeIntervalSince1970,
            uploadState: .none,
            assetId: nil
        )
        var index = loadIndex()
        index.insert(record, at: 0)
        saveIndex(index)
        return record
    }

    static func update(id: String, uploadState: ReadingPhotoUploadState, assetId: String? = nil) {
        var index = loadIndex()
        guard let idx = index.firstIndex(where: { $0.id == id }) else { return }
        index[idx].uploadState = uploadState
        if let assetId = assetId {
            index[idx].assetId = assetId
        }
        saveIndex(index)
    }

    static func thumbnail(for id: String) -> UIImage? {
        guard let data = try? Data(contentsOf: fileURL(for: id)) else { return nil }
        return UIImage(data: data)
    }

    private static func loadIndex() -> [ReadingPhotoRecord] {
        guard let data = UserDefaults.standard.data(forKey: indexKey) else { return [] }
        return (try? JSONDecoder().decode([ReadingPhotoRecord].self, from: data)) ?? []
    }

    private static func saveIndex(_ records: [ReadingPhotoRecord]) {
        guard let data = try? JSONEncoder().encode(records) else { return }
        UserDefaults.standard.set(data, forKey: indexKey)
    }
}
