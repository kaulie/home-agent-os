package com.smarthome.livingroom_android.capability

/**
 * Wire vocabulary for living-room-android (slim Edge).
 */
object Capabilities {
    // network.wifi
    const val WIFI_JOIN = "network.wifi.join"
    const val WIFI_LEAVE = "network.wifi.leave"

    // known but not executed here (tracked / skipped)
    const val CAMERA_CAPTURE = "camera.capture"
    const val CAMERA_CAPTURE_AND_UPLOAD = "camera.capture_and_upload"
    const val TAKE_VIDEO = "take_video"
    const val DISPLAY_PHOTO = "display.photo"
    const val MUSIC_PLAY = "music.play"
    const val MUSIC_PAUSE = "music.pause"
    const val MUSIC_STOP = "music.stop"
    const val MUSIC_NEXT = "music.next"
    const val MUSIC_PREVIOUS = "music.previous"
    const val BLUETOOTH_CONNECT = "bluetooth.connect"
    const val BLUETOOTH_DISCONNECT = "bluetooth.disconnect"

    const val DOCUMENT_SCAN = "document.scan"
    const val VISUAL_INPUT = "visual.input"
    const val PHONE_CALL = "phone.call"
    const val ASSET_UPLOAD = "asset.upload"

    val WIFI_ALL = setOf(WIFI_JOIN, WIFI_LEAVE)
    val CAMERA_ALL = setOf(CAMERA_CAPTURE, TAKE_VIDEO, CAMERA_CAPTURE_AND_UPLOAD)
    val DISPLAY_ALL = setOf(DISPLAY_PHOTO)
    val MUSIC_ALL = setOf(MUSIC_PLAY, MUSIC_PAUSE, MUSIC_STOP, MUSIC_NEXT, MUSIC_PREVIOUS)
    val BLUETOOTH_ALL = setOf(BLUETOOTH_CONNECT, BLUETOOTH_DISCONNECT)
    val SCAN_ALL = setOf(DOCUMENT_SCAN, VISUAL_INPUT)
}
