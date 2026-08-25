package com.smarthome.livingroom_v2.skill.music

/**
 * music.play success rules for Chromecast / phone.
 * startActivity / am start returning is not playback.
 */
object NetEasePlayPolicy {
    const val PHONE_PACKAGE = "com.netease.cloudmusic"
    const val LITE_PACKAGE = "com.netease.cloudmusic.lite"
    const val TV_PACKAGE = "com.netease.cloudmusic.tv"

    fun isNeteasePackage(packageName: String): Boolean {
        val lower = packageName.lowercase()
        return lower == PHONE_PACKAGE || lower == LITE_PACKAGE || lower == TV_PACKAGE
    }

    /** Deep-link methods that actually resolved an Activity. Others are "command accepted". */
    fun countsAsResolvedOpen(method: String?): Boolean =
        method == "explicit" || method == "intentUri"

    fun playbackConfirmed(musicActive: Boolean): Boolean = musicActive
}
