import Foundation

/// Shared wire vocabulary with Android `Capabilities`.
/// Ads come from each Skill.service().capabilities — not from this enum alone.
enum Capabilities {
    // music (netease.music)
    static let musicPlay = "music.play"
    static let musicPause = "music.pause"
    static let musicStop = "music.stop"
    static let musicNext = "music.next"
    static let musicPrevious = "music.previous"

    // speaker (marshall.willen)
    static let bluetoothConnect = "bluetooth.connect"
    static let bluetoothDisconnect = "bluetooth.disconnect"

    // camera (gopro.camera)
    static let cameraCapture = "camera.capture"
    static let takeVideo = "take_video"

    // display (chromecast.display) — iPhone Cast Sender
    static let displayPhoto = "display.photo"

    // system (iphone helpers)
    static let intentDispatch = "intent.dispatch"
    static let commandsPull = "commands.pull"
    static let commandsExecute = "commands.execute"

    static let musicAll: Set<String> = [
        musicPlay, musicPause, musicStop, musicNext, musicPrevious,
    ]
    static let bluetoothAll: Set<String> = [bluetoothConnect, bluetoothDisconnect]
    static let cameraAll: Set<String> = [cameraCapture, takeVideo]
    static let displayAll: Set<String> = [displayPhoto]

    private static let descriptions: [String: String] = [
        musicPlay: "按歌曲 / 专辑 / 歌手播放网易云",
        musicPause: "暂停播放",
        musicStop: "停止播放",
        musicNext: "下一首",
        musicPrevious: "上一首",
        cameraCapture: "拍照、下载并上传，产出 photo_url",
        takeVideo: "开始录像",
        displayPhoto: "将 photo_url 经 Cast 投到 Chromecast",
        bluetoothConnect: "连接蓝牙音箱",
        bluetoothDisconnect: "断开蓝牙音箱",
        intentDispatch: "用户意图上报与分发",
        commandsPull: "从服务器拉取设备指令",
        commandsExecute: "执行已拉取的指令 JSON",
    ]

    static func describe(_ capabilityId: String) -> String {
        descriptions[capabilityId] ?? capabilityId
    }
}
