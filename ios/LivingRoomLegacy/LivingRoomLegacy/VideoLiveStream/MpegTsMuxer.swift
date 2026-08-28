import Foundation

/// MPEG-TS muxer for H.264 Annex-B access units (188-byte packets).
final class MpegTsMuxer {
    static let packetSize = 188
    private static let patPid: UInt16 = 0x0000
    private static let pmtPid: UInt16 = 0x1000
    private static let videoPid: UInt16 = 0x0100

    private var patCc: UInt8 = 0
    private var pmtCc: UInt8 = 0
    private var videoCc: UInt8 = 0
    private var frameIndex = 0
    var includesAudio = false

    func reset() {
        patCc = 0
        pmtCc = 0
        videoCc = 0
        frameIndex = 0
    }

    func mux(annexB: Data, pts90k: UInt64, keyframe: Bool) -> Data {
        var out = Data()
        if keyframe || frameIndex % 30 == 0 {
            out.append(patPacket())
            out.append(pmtPacket())
        }
        let pes = Self.pesPacket(annexB: annexB, pts90k: pts90k)
        frameIndex += 1
        out.append(
            packetize(
                pid: Self.videoPid,
                payload: pes,
                pcr90k: keyframe ? pts90k : nil,
                pusi: true
            )
        )
        return out
    }

    private func patPacket() -> Data {
        var section = Data()
        section.append(0x00)
        section.append(contentsOf: [0xB0, 0x0D])
        section.append(contentsOf: [0x00, 0x01])
        section.append(0xC1)
        section.append(0x00)
        section.append(0x00)
        section.append(contentsOf: [0x00, 0x01])
        section.append(0xE0 | UInt8((Self.pmtPid >> 8) & 0x1F))
        section.append(UInt8(Self.pmtPid & 0xFF))
        let crc = Self.mpegCrc32(section)
        section.append(contentsOf: crc.bigEndianBytes)
        return wrapPsi(pid: Self.patPid, section: section, cc: &patCc)
    }

    private func pmtPacket() -> Data {
        var section = Data()
        section.append(0x02)
        let lengthIndex = section.count
        section.append(contentsOf: [0xB0, 0x00])
        section.append(contentsOf: [0x00, 0x01])
        section.append(0xC1)
        section.append(0x00)
        section.append(0x00)
        section.append(0xE0 | UInt8((Self.videoPid >> 8) & 0x1F))
        section.append(UInt8(Self.videoPid & 0xFF))
        section.append(contentsOf: [0xF0, 0x00])
        section.append(0x1B)
        section.append(0xE0 | UInt8((Self.videoPid >> 8) & 0x1F))
        section.append(UInt8(Self.videoPid & 0xFF))
        section.append(contentsOf: [0xF0, 0x00])
        let sectionLength = section.count - 3 + 4
        section[lengthIndex] = 0xB0 | UInt8((sectionLength >> 8) & 0x0F)
        section[lengthIndex + 1] = UInt8(sectionLength & 0xFF)
        let crc = Self.mpegCrc32(section)
        section.append(contentsOf: crc.bigEndianBytes)
        return wrapPsi(pid: Self.pmtPid, section: section, cc: &pmtCc)
    }

    private func wrapPsi(pid: UInt16, section: Data, cc: inout UInt8) -> Data {
        var payload = Data([0x00])
        payload.append(section)
        return packetize(pid: pid, payload: payload, pcr90k: nil, pusi: true, cc: &cc)
    }

    private func packetize(
        pid: UInt16,
        payload: Data,
        pcr90k: UInt64?,
        pusi: Bool,
        cc: inout UInt8
    ) -> Data {
        var remaining = payload
        var first = true
        var out = Data()
        while !remaining.isEmpty || first {
            var packet = Data(count: Self.packetSize)
            packet[0] = 0x47
            let pusiBit: UInt8 = (pusi && first) ? 0x40 : 0x00
            packet[1] = pusiBit | UInt8((pid >> 8) & 0x1F)
            packet[2] = UInt8(pid & 0xFF)
            var offset = 4
            let writePCR = first && pcr90k != nil
            let leftover = remaining.count
            let headerRoom = 184
            if writePCR || leftover < headerRoom {
                var adaptLen = 1
                if writePCR { adaptLen += 6 }
                let payloadBytes: Int
                if leftover >= headerRoom - (1 + adaptLen) {
                    payloadBytes = headerRoom - (1 + adaptLen)
                } else {
                    payloadBytes = leftover
                }
                let stuffing = headerRoom - 1 - adaptLen - payloadBytes
                adaptLen += stuffing
                packet[3] = 0x30 | (cc & 0x0F)
                packet[4] = UInt8(adaptLen)
                packet[5] = writePCR ? 0x10 : 0x00
                offset = 6
                if writePCR, let pcr = pcr90k {
                    let pcrBytes = Self.pcrBytes(pcr90k: pcr)
                    packet.replaceSubrange(offset..<(offset + 6), with: pcrBytes)
                    offset += 6
                }
                if stuffing > 0 {
                    for i in 0..<stuffing {
                        packet[offset + i] = 0xFF
                    }
                    offset += stuffing
                }
                if payloadBytes > 0 {
                    packet.replaceSubrange(offset..<(offset + payloadBytes), with: remaining.prefix(payloadBytes))
                    remaining.removeFirst(payloadBytes)
                }
            } else {
                packet[3] = 0x10 | (cc & 0x0F)
                packet.replaceSubrange(4..<Self.packetSize, with: remaining.prefix(184))
                remaining.removeFirst(184)
            }
            cc = (cc + 1) & 0x0F
            out.append(packet)
            first = false
            if remaining.isEmpty { break }
        }
        return out
    }

    private func packetize(pid: UInt16, payload: Data, pcr90k: UInt64?, pusi: Bool) -> Data {
        packetize(pid: pid, payload: payload, pcr90k: pcr90k, pusi: pusi, cc: &videoCc)
    }

    private static func pesPacket(annexB: Data, pts90k: UInt64) -> Data {
        var pes = Data([0x00, 0x00, 0x01, 0xE0])
        pes.append(contentsOf: [0x00, 0x00])
        pes.append(0x80)
        pes.append(0x80)
        pes.append(0x05)
        pes.append(contentsOf: ptsBytes(pts90k))
        pes.append(annexB)
        return pes
    }

    private static func ptsBytes(_ pts: UInt64) -> Data {
        var b = Data(count: 5)
        b[0] = 0x20 | UInt8(((pts >> 30) & 0x07) << 1) | 0x01
        b[1] = UInt8((pts >> 22) & 0xFF)
        b[2] = UInt8(((pts >> 15) & 0x7F) << 1) | 0x01
        b[3] = UInt8((pts >> 7) & 0xFF)
        b[4] = UInt8((pts & 0x7F) << 1) | 0x01
        return b
    }

    private static func pcrBytes(pcr90k: UInt64) -> Data {
        var b = Data(count: 6)
        b[0] = UInt8((pcr90k >> 25) & 0xFF)
        b[1] = UInt8((pcr90k >> 17) & 0xFF)
        b[2] = UInt8((pcr90k >> 9) & 0xFF)
        b[3] = UInt8((pcr90k >> 1) & 0xFF)
        b[4] = UInt8(((pcr90k & 0x1) << 7) | 0x7E)
        b[5] = 0
        return b
    }

    private static func mpegCrc32(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for byte in data {
            crc ^= UInt32(byte) << 24
            for _ in 0..<8 {
                if crc & 0x8000_0000 != 0 {
                    crc = (crc << 1) ^ 0x04C11DB7
                } else {
                    crc <<= 1
                }
            }
        }
        return crc
    }
}

private extension UInt32 {
    var bigEndianBytes: [UInt8] {
        [
            UInt8((self >> 24) & 0xFF),
            UInt8((self >> 16) & 0xFF),
            UInt8((self >> 8) & 0xFF),
            UInt8(self & 0xFF),
        ]
    }
}
