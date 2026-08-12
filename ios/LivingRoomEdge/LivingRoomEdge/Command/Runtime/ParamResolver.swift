import Foundation

enum ParamResolverError: Error, LocalizedError, Equatable {
    case unresolvedVariable(String)
    case unsupportedTemplate(String)

    var errorDescription: String? {
        switch self {
        case .unresolvedVariable(let name):
            return "unresolved context variable $\(name)"
        case .unsupportedTemplate(let value):
            return "unsupported param template (use $var): \(value)"
        }
    }
}

/// Resolves whole-value param references from `RuntimeContext`.
/// Supports `$name` / `${name}`; rejects `{{...}}` (e.g. stepN.output).
enum ParamResolver {
    private static let dollarName = try! NSRegularExpression(
        pattern: #"^\$([A-Za-z_][A-Za-z0-9_]*)$"#
    )
    private static let dollarBrace = try! NSRegularExpression(
        pattern: #"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$"#
    )

    static func resolve(params: [String: String], context: RuntimeContext) throws -> [String: String] {
        var out: [String: String] = [:]
        out.reserveCapacity(params.count)
        for (key, raw) in params {
            out[key] = try resolveValue(raw, context: context)
        }
        return out
    }

    static func resolveValue(_ raw: String, context: RuntimeContext) throws -> String {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.contains("{{") || value.contains("}}") {
            throw ParamResolverError.unsupportedTemplate(value)
        }
        if let name = matchVariable(value) {
            guard let resolved = context.get(name) else {
                throw ParamResolverError.unresolvedVariable(name)
            }
            return resolved
        }
        return raw
    }

    private static func matchVariable(_ value: String) -> String? {
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        if let m = dollarName.firstMatch(in: value, options: [], range: range),
           let r = Range(m.range(at: 1), in: value)
        {
            return String(value[r])
        }
        if let m = dollarBrace.firstMatch(in: value, options: [], range: range),
           let r = Range(m.range(at: 1), in: value)
        {
            return String(value[r])
        }
        return nil
    }
}
