import Foundation

enum VideoLiveError: LocalizedError {
    case message(String)

    var errorDescription: String? {
        switch self {
        case .message(let s): return s
        }
    }
}
