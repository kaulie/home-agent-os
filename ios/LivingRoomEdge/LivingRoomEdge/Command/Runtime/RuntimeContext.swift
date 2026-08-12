import Foundation

/// Shared variables for an intent across `CommandHandler.handle` calls.
/// Only fields listed in plan-step `output_constrict` with `data_dest: "context"` are published.
final class RuntimeContext {
    private var values: [String: String] = [:]

    func get(_ key: String) -> String? {
        let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !k.isEmpty else { return nil }
        let v = values[k]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return v.isEmpty ? nil : v
    }

    func snapshot() -> [String: String] {
        values
    }

    /// Publish skill outputs whose keys appear in `output_constrict` with `data_dest == "context"`.
    /// Empty constrict → publish nothing.
    @discardableResult
    func publish(outputs: [String: String], constrict: [String: OutputConstrictField]) -> [String] {
        guard !constrict.isEmpty, !outputs.isEmpty else { return [] }
        var published: [String] = []
        for (key, field) in constrict {
            guard field.publishesToContext else { continue }
            let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !k.isEmpty else { continue }
            let value = outputs[k]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !value.isEmpty else { continue }
            values[k] = value
            published.append(k)
        }
        return published
    }
}
