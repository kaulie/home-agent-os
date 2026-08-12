import Foundation

struct NetEaseSongHit: Sendable {
    let id: Int64
    let name: String
    let artists: String
}

struct NetEaseAlbumHit: Sendable {
    let id: Int64
    let name: String
    let artists: String
    let firstSongId: Int64?
}

/// Resolves song / artist / album queries to NetEase ids (mirrors Android NetEaseSearchClient).
final class NetEaseSearchClient: @unchecked Sendable {
    private let session: URLSession
    private let userAgent =
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Strategy 1: search single track (type=1), optional artist weighting.
    func searchBest(song: String, artist: String?) async throws -> NetEaseSongHit {
        let songQuery = song.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !songQuery.isEmpty else { throw SearchError.message("song is required") }
        let artistQuery = artist?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        var hits: [Int64: NetEaseSongHit] = [:]
        for hit in try await fetchSongSearch(song: songQuery, artist: artistQuery) {
            hits[hit.id] = hit
        }
        guard !hits.isEmpty else {
            throw SearchError.message("网易云未找到歌曲: \(songQuery) \(artistQuery)")
        }

        let chosen = hits.values.max(by: { scoreSongHit($0, song: songQuery, artist: artistQuery) < scoreSongHit($1, song: songQuery, artist: artistQuery) })!
        let score = scoreSongHit(chosen, song: songQuery, artist: artistQuery)
        if !artistQuery.isEmpty && score < 80 {
            throw SearchError.message(
                "未找到足够匹配「\(songQuery) - \(artistQuery)」的结果，最接近: \(chosen.name) - \(chosen.artists)"
            )
        }
        return chosen
    }

    /// Strategy 2: search album (type=10); optional artist filter.
    func searchBestAlbum(album: String, artist: String?) async throws -> NetEaseAlbumHit {
        let albumQuery = album.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !albumQuery.isEmpty else { throw SearchError.message("album is required") }
        let artistQuery = artist?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        let hits = try await fetchAlbumSearch(album: albumQuery, artist: artistQuery)
        guard !hits.isEmpty else {
            throw SearchError.message("网易云未找到专辑: \(albumQuery) \(artistQuery)")
        }

        let chosen = hits.max(by: { scoreAlbumHit($0, album: albumQuery, artist: artistQuery) < scoreAlbumHit($1, album: albumQuery, artist: artistQuery) })!
        let score = scoreAlbumHit(chosen, album: albumQuery, artist: artistQuery)
        if !artistQuery.isEmpty && score < 80 {
            throw SearchError.message(
                "未找到足够匹配专辑「\(albumQuery) - \(artistQuery)」的结果，最接近: \(chosen.name) - \(chosen.artists)"
            )
        }

        if chosen.firstSongId != nil {
            return chosen
        }
        let firstSongId = try? await fetchAlbumFirstSongId(albumId: chosen.id)
        return NetEaseAlbumHit(
            id: chosen.id,
            name: chosen.name,
            artists: chosen.artists,
            firstSongId: firstSongId
        )
    }

    /// Strategy 3: artist-only — search tracks with artist as query.
    func searchBestByArtist(artist: String) async throws -> NetEaseSongHit {
        let artistQuery = artist.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !artistQuery.isEmpty else { throw SearchError.message("artist is required") }

        var hits: [Int64: NetEaseSongHit] = [:]
        for hit in try await fetchSongSearch(song: artistQuery, artist: artistQuery) {
            hits[hit.id] = hit
        }
        for hit in try await fetchSongSearchRaw(query: artistQuery) {
            hits[hit.id] = hits[hit.id] ?? hit
        }
        guard !hits.isEmpty else {
            throw SearchError.message("网易云未找到歌手曲目: \(artistQuery)")
        }

        let chosen = hits.values.max(by: { scoreSongHit($0, song: "", artist: artistQuery) < scoreSongHit($1, song: "", artist: artistQuery) })!
        let score = scoreSongHit(chosen, song: "", artist: artistQuery)
        if score < 80 {
            throw SearchError.message(
                "未找到足够匹配歌手「\(artistQuery)」的结果，最接近: \(chosen.name) - \(chosen.artists)"
            )
        }
        return chosen
    }

    private enum SearchError: LocalizedError {
        case message(String)
        var errorDescription: String? {
            switch self {
            case .message(let m): return m
            }
        }
    }

    private func fetchSongSearch(song: String, artist: String) async throws -> [NetEaseSongHit] {
        let query = artist.isEmpty ? song : "\(song) \(artist)"
        return try await fetchSongSearchRaw(query: query)
    }

    private func fetchSongSearchRaw(query: String) async throws -> [NetEaseSongHit] {
        var hits: [Int64: NetEaseSongHit] = [:]
        for hit in try parseSongs(await fetchCloudSearch(query: query, type: 1)) {
            hits[hit.id] = hit
        }
        for hit in try parseSongs(await fetchWebSearch(query: query, type: 1)) {
            if hits[hit.id] == nil { hits[hit.id] = hit }
        }
        return Array(hits.values)
    }

    private func fetchAlbumSearch(album: String, artist: String) async throws -> [NetEaseAlbumHit] {
        let query = artist.isEmpty ? album : "\(album) \(artist)"
        var hits: [Int64: NetEaseAlbumHit] = [:]
        for hit in try parseAlbums(await fetchCloudSearch(query: query, type: 10)) {
            hits[hit.id] = hit
        }
        for hit in try parseAlbums(await fetchWebSearch(query: query, type: 10)) {
            if hits[hit.id] == nil { hits[hit.id] = hit }
        }
        return Array(hits.values)
    }

    private func fetchWebSearch(query: String, type: Int) async throws -> Data {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=?")
        let encoded = query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query
        let url = URL(string: "https://music.163.com/api/search/get/web?s=\(encoded)&type=\(type)&offset=0&total=true&limit=20")!
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://music.163.com", forHTTPHeaderField: "Referer")
        return try await execute(request)
    }

    private func fetchCloudSearch(query: String, type: Int) async throws -> Data {
        let url = URL(string: "https://music.163.com/api/cloudsearch/pc")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://music.163.com", forHTTPHeaderField: "Referer")
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        let body = "s=\(formEncode(query))&type=\(type)&limit=20&offset=0"
        request.httpBody = body.data(using: .utf8)
        return try await execute(request)
    }

    private func fetchAlbumFirstSongId(albumId: Int64) async throws -> Int64? {
        let url = URL(string: "https://music.163.com/api/album/\(albumId)")!
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://music.163.com", forHTTPHeaderField: "Referer")
        let data = try await execute(request)
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let songs = (json["album"] as? [String: Any])?["songs"] as? [[String: Any]]
            ?? json["songs"] as? [[String: Any]]
        guard let first = songs?.first else { return nil }
        if let id = first["id"] as? Int64 { return id }
        if let id = first["id"] as? Int { return Int64(id) }
        if let id = first["id"] as? NSNumber { return id.int64Value }
        return nil
    }

    private func execute(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw SearchError.message("网易云搜索失败: HTTP \(http.statusCode)")
        }
        return data
    }

    private func formEncode(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    private func parseSongs(_ data: Data) throws -> [NetEaseSongHit] {
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let result = json["result"] as? [String: Any],
              let songs = result["songs"] as? [[String: Any]] else {
            return []
        }
        return songs.compactMap { item in
            guard let id = int64(item["id"]) else { return nil }
            let artistsArr = item["artists"] as? [[String: Any]] ?? item["ar"] as? [[String: Any]]
            return NetEaseSongHit(
                id: id,
                name: item["name"] as? String ?? "",
                artists: joinArtistNames(artistsArr)
            )
        }
    }

    private func parseAlbums(_ data: Data) throws -> [NetEaseAlbumHit] {
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let result = json["result"] as? [String: Any],
              let albums = result["albums"] as? [[String: Any]] else {
            return []
        }
        return albums.compactMap { item in
            guard let id = int64(item["id"]) else { return nil }
            let artistNames: String
            if let artists = item["artists"] as? [[String: Any]] {
                artistNames = joinArtistNames(artists)
            } else if let artist = item["artist"] as? [String: Any] {
                artistNames = artist["name"] as? String ?? ""
            } else {
                artistNames = ""
            }
            var firstSongId: Int64?
            if let songs = item["songs"] as? [[String: Any]], let first = songs.first {
                firstSongId = int64(first["id"])
            }
            return NetEaseAlbumHit(
                id: id,
                name: item["name"] as? String ?? "",
                artists: artistNames,
                firstSongId: firstSongId
            )
        }
    }

    private func joinArtistNames(_ artists: [[String: Any]]?) -> String {
        guard let artists, !artists.isEmpty else { return "" }
        return artists.compactMap { $0["name"] as? String }.joined(separator: " / ")
    }

    private func int64(_ any: Any?) -> Int64? {
        switch any {
        case let v as Int64: return v
        case let v as Int: return Int64(v)
        case let v as NSNumber: return v.int64Value
        default: return nil
        }
    }

    private func scoreSongHit(_ hit: NetEaseSongHit, song: String, artist: String) -> Int {
        var score = 0
        let name = hit.name.lowercased()
        let artists = hit.artists.lowercased()
        let songL = song.lowercased()
        let artistL = artist.lowercased()

        if !songL.isEmpty {
            if name == songL { score += 100 }
            else if name.contains(songL) { score += 70 }
            else if songL.contains(name) { score += 30 }
        }

        if !artistL.isEmpty {
            if artists == artistL { score += 120 }
            else if artists.contains(artistL) { score += 100 }
            else if name.contains(artistL) { score += 95 }
            else if name.contains("翻自") && name.contains(artistL) { score += 110 }
            else { score -= 50 }
        }
        return score
    }

    private func scoreAlbumHit(_ hit: NetEaseAlbumHit, album: String, artist: String) -> Int {
        var score = 0
        let name = hit.name.lowercased()
        let artists = hit.artists.lowercased()
        let albumL = album.lowercased()
        let artistL = artist.lowercased()

        if name == albumL { score += 100 }
        else if name.contains(albumL) { score += 70 }
        else if albumL.contains(name) { score += 30 }

        if !artistL.isEmpty {
            if artists == artistL { score += 120 }
            else if artists.contains(artistL) { score += 100 }
            else { score -= 50 }
        }
        return score
    }
}
