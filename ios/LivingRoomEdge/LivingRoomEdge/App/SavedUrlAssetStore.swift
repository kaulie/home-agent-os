import Combine
import Foundation

/// 文件页「已存链接」：Brain url 资产的本机快捷列表（asset 仍以 Brain 为准；
/// 删除只移除本机条目，不删 Brain 资产）。
struct SavedUrlAsset: Identifiable, Equatable, Codable {
    let id: UUID
    let assetId: String
    let url: String
    var title: String
    let createdAt: Date
}

@MainActor
final class SavedUrlAssetStore: ObservableObject {
    @Published private(set) var items: [SavedUrlAsset] = []

    private let storageKey = "livingroom.savedUrlAssets.v1"

    init() {
        load()
    }

    func add(_ item: SavedUrlAsset) {
        items.insert(item, at: 0)
        persist()
    }

    func remove(id: UUID) {
        items.removeAll { $0.id == id }
        persist()
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let rows = try? JSONDecoder().decode([SavedUrlAsset].self, from: data)
        else {
            return
        }
        items = rows.sorted { $0.createdAt > $1.createdAt }
    }

    private func persist() {
        let rows = Array(items.prefix(60))
        if let data = try? JSONEncoder().encode(rows) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }
}
