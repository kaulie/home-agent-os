import Foundation

/// NetEase via API search + app deep link.
/// music.play strategies (priority): song → album → artist-only.
final class NetEaseMusicSkill: Skill {
    static let skillId = "netease.music"

    private let search: NetEaseSearchClient

    init(search: NetEaseSearchClient = NetEaseSearchClient()) {
        self.search = search
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.3.0",
            displayName: "网易云音乐",
            group: "music",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: Capabilities.musicPlay,
                    description: "按歌曲 / 专辑 / 歌手播放网易云",
                    inputSchema: [
                        "song": SchemaField(type: "string", required: false, description: "歌曲"),
                        "artist": SchemaField(type: "string", required: false, description: "歌手"),
                        "album": SchemaField(type: "string", required: false, description: "专辑"),
                    ]
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.musicPause,
                    description: Capabilities.describe(Capabilities.musicPause)
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.musicStop,
                    description: Capabilities.describe(Capabilities.musicStop)
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.musicNext,
                    description: Capabilities.describe(Capabilities.musicNext)
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.musicPrevious,
                    description: Capabilities.describe(Capabilities.musicPrevious)
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        switch capabilityId {
        case Capabilities.musicPlay:
            return await playMusic(params)
        case Capabilities.musicPause:
            return .ok("media pause（请在网易云 / 控制中心操作）")
        case Capabilities.musicStop:
            return .ok("media stop（请在网易云 / 控制中心操作）")
        case Capabilities.musicNext:
            return .ok("media next（请在网易云 / 控制中心操作）")
        case Capabilities.musicPrevious:
            return .ok("media previous（请在网易云 / 控制中心操作）")
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }

    private func playMusic(_ params: [String: String]) async -> SkillResult {
        let song = trim(params["song"])
        let artist = trim(params["artist"])
        let album = trim(params["album"])
        if song.isEmpty && artist.isEmpty && album.isEmpty {
            return .error("\(Capabilities.musicPlay) requires song, artist, or album")
        }

        if !song.isEmpty {
            return await playBySong(song, artist: artist.isEmpty ? nil : artist)
        }
        if !album.isEmpty {
            return await playByAlbum(album, artist: artist.isEmpty ? nil : artist)
        }
        return await playByArtist(artist)
    }

    private func playBySong(_ song: String, artist: String?) async -> SkillResult {
        let label = artist.map { "「\(song) - \($0)」" } ?? "「\(song)」"
        let hit: NetEaseSongHit
        do {
            hit = try await search.searchBest(song: song, artist: artist)
        } catch {
            return .error("搜歌失败: \(error.localizedDescription)")
        }
        return await openSong(hit, label: label)
    }

    private func playByAlbum(_ album: String, artist: String?) async -> SkillResult {
        let label = artist.map { "专辑「\(album) - \($0)」" } ?? "专辑「\(album)」"
        let hit: NetEaseAlbumHit
        do {
            hit = try await search.searchBestAlbum(album: album, artist: artist)
        } catch {
            return .error("搜专辑失败: \(error.localizedDescription)")
        }
        let opened = await NetEaseDeepLinkLauncher.openAlbum(
            albumId: hit.id,
            fallbackSongId: hit.firstSongId
        )
        guard opened.success else {
            return .error("深链失败: \(opened.detail ?? "unknown")（需安装网易云）")
        }
        return .ok(
            "深链已打开 \(label) → album#\(hit.id) \(hit.name) - \(hit.artists)"
                + " via \(opened.method ?? "?")"
        )
    }

    private func playByArtist(_ artist: String) async -> SkillResult {
        let label = "歌手「\(artist)」"
        let hit: NetEaseSongHit
        do {
            hit = try await search.searchBestByArtist(artist: artist)
        } catch {
            return .error("搜歌手失败: \(error.localizedDescription)")
        }
        return await openSong(hit, label: label)
    }

    private func openSong(_ hit: NetEaseSongHit, label: String) async -> SkillResult {
        let opened = await NetEaseDeepLinkLauncher.openSong(songId: hit.id)
        guard opened.success else {
            return .error("深链失败: \(opened.detail ?? "unknown")（需安装网易云）")
        }
        return .ok(
            "深链已打开 \(label) → #\(hit.id) \(hit.name) - \(hit.artists)"
                + " via \(opened.method ?? "?")"
        )
    }

    private func trim(_ value: String?) -> String {
        value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
}
