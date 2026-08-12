package com.smarthome.livingroom_v2.capability

/**
 * Shared wire vocabulary with iOS `Capabilities`.
 * Ads come from each Skill.service().capabilities — not from this object alone.
 */
object Capabilities {
    // music (netease.music)
    const val MUSIC_PLAY = "music.play"
    const val MUSIC_PAUSE = "music.pause"
    const val MUSIC_STOP = "music.stop"
    const val MUSIC_NEXT = "music.next"
    const val MUSIC_PREVIOUS = "music.previous"

    // speaker (marshall.willen)
    const val BLUETOOTH_CONNECT = "bluetooth.connect"
    const val BLUETOOTH_DISCONNECT = "bluetooth.disconnect"

    // camera (gopro.camera)
    const val CAMERA_CAPTURE = "camera.capture"
    const val TAKE_VIDEO = "take_video"

    // display (chromecast.display)
    const val DISPLAY_PHOTO = "display.photo"

    // system (iphone helpers)
    const val INTENT_DISPATCH = "intent.dispatch"
    const val COMMANDS_PULL = "commands.pull"
    const val COMMANDS_EXECUTE = "commands.execute"

    val MUSIC_ALL = setOf(MUSIC_PLAY, MUSIC_PAUSE, MUSIC_STOP, MUSIC_NEXT, MUSIC_PREVIOUS)
    val BLUETOOTH_ALL = setOf(BLUETOOTH_CONNECT, BLUETOOTH_DISCONNECT)
    val CAMERA_ALL = setOf(CAMERA_CAPTURE, TAKE_VIDEO)
    val DISPLAY_ALL = setOf(DISPLAY_PHOTO)
}
