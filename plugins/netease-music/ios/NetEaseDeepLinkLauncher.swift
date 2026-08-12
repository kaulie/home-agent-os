import Foundation
import UIKit

/// Opens NetEase iOS app via orpheus / https links (mirrors Android NetEaseDeepLinkLauncher).
enum NetEaseDeepLinkLauncher {
    struct OpenResult: Sendable {
        let success: Bool
        let uri: String?
        let method: String?
        let detail: String?
    }

    @MainActor
    static func openSong(songId: Int64) async -> OpenResult {
        await openUris(songUriCandidates(songId))
    }

    /// Open album; if album deep link fails and fallbackSongId is set, open that track.
    @MainActor
    static func openAlbum(albumId: Int64, fallbackSongId: Int64?) async -> OpenResult {
        let albumResult = await openUris(albumUriCandidates(albumId))
        if albumResult.success { return albumResult }
        if let fallbackSongId, fallbackSongId > 0 {
            return await openSong(songId: fallbackSongId)
        }
        return albumResult
    }

    @MainActor
    private static func openUris(_ uris: [String]) async -> OpenResult {
        var errors: [String] = []
        for uri in uris {
            guard let url = URL(string: uri) else {
                errors.append("bad:\(uri)")
                continue
            }
            let canOpen = UIApplication.shared.canOpenURL(url)
            if !canOpen && uri.hasPrefix("orpheus://") {
                errors.append("no-handler:\(uri)")
                continue
            }
            let ok = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
                UIApplication.shared.open(url, options: [:]) { success in
                    cont.resume(returning: success)
                }
            }
            if ok {
                return OpenResult(success: true, uri: uri, method: "openURL", detail: nil)
            }
            errors.append("fail:\(uri)")
        }
        return OpenResult(
            success: false,
            uri: nil,
            method: nil,
            detail: errors.prefix(4).joined(separator: "; ")
        )
    }

    private static func songUriCandidates(_ songId: Int64) -> [String] {
        [
            "orpheus://song/\(songId)/?autoplay=1",
            "orpheus://song/\(songId)?autoplay=1",
            "orpheus://song/\(songId)",
            "https://music.163.com/song?id=\(songId)",
            "https://music.163.com/m/song/\(songId)",
        ]
    }

    private static func albumUriCandidates(_ albumId: Int64) -> [String] {
        [
            "orpheus://album/\(albumId)/?autoplay=1",
            "orpheus://album/\(albumId)?autoplay=1",
            "orpheus://album/\(albumId)",
            "https://music.163.com/album?id=\(albumId)",
            "https://music.163.com/m/album/\(albumId)",
        ]
    }
}
