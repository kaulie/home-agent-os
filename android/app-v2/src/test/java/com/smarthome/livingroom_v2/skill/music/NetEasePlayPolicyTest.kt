package com.smarthome.livingroom_v2.skill.music

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetEasePlayPolicyTest {
    @Test
    fun startActivityAndShellAmAreNotResolvedOpens() {
        assertFalse(NetEasePlayPolicy.countsAsResolvedOpen("startActivity"))
        assertFalse(NetEasePlayPolicy.countsAsResolvedOpen("shell_am"))
        assertTrue(NetEasePlayPolicy.countsAsResolvedOpen("explicit"))
        assertTrue(NetEasePlayPolicy.countsAsResolvedOpen("intentUri"))
    }

    @Test
    fun silentOutputIsNotPlayback() {
        assertFalse(NetEasePlayPolicy.playbackConfirmed(false))
        assertTrue(NetEasePlayPolicy.playbackConfirmed(true))
    }

    @Test
    fun tvAndPhonePackagesCountAsNetease() {
        assertTrue(NetEasePlayPolicy.isNeteasePackage("com.netease.cloudmusic"))
        assertTrue(NetEasePlayPolicy.isNeteasePackage("com.netease.cloudmusic.tv"))
        assertTrue(NetEasePlayPolicy.isNeteasePackage("com.netease.cloudmusic.lite"))
        assertFalse(NetEasePlayPolicy.isNeteasePackage("com.android.chrome"))
    }
}
