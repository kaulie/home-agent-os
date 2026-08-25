import Foundation

/// Last successful `GET intent_detail` body per intent id (offline / cold-start progress UI).
enum IntentDetailCache {
    private static let indexKey = "livingroom.intentDetailCache.index.v1"
    private static let maxEntries = 80

    static func save(intentId: String, data: Data) {
        let key = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, !data.isEmpty else { return }
        var index = loadIndex()
        index.removeAll { $0 == key }
        index.append(key)
        while index.count > maxEntries, let drop = index.first {
            index.removeFirst()
            UserDefaults.standard.removeObject(forKey: storageKey(drop))
        }
        UserDefaults.standard.set(index, forKey: indexKey)
        UserDefaults.standard.set(data, forKey: storageKey(key))
    }

    static func snapshot(for intentId: String) -> IntentJobSnapshot? {
        let key = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty,
              let data = UserDefaults.standard.data(forKey: storageKey(key))
        else { return nil }
        return IntentJobSnapshot.parse(data: data)
    }

    static func clear() {
        for key in loadIndex() {
            UserDefaults.standard.removeObject(forKey: storageKey(key))
        }
        UserDefaults.standard.removeObject(forKey: indexKey)
    }

    private static func storageKey(_ intentId: String) -> String {
        "livingroom.intentDetailCache.body.\(intentId)"
    }

    private static func loadIndex() -> [String] {
        UserDefaults.standard.stringArray(forKey: indexKey) ?? []
    }
}
