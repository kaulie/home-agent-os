package com.smarthome.livingroom_android.skill

import java.io.File
import java.util.concurrent.ConcurrentHashMap

/** Files produced by camera.capture on this device for a later asset.upload step. */
object LocalCaptureAssets {
    private val files = ConcurrentHashMap<String, File>()

    fun remember(assetId: String, file: File) {
        val aid = assetId.trim()
        if (aid.isEmpty()) return
        files[aid] = file
    }

    fun file(assetId: String): File? {
        val aid = assetId.trim()
        val stored = files[aid] ?: return null
        return stored.takeIf { it.isFile && it.length() > 0 }
    }

    fun bytes(assetId: String): ByteArray? {
        val f = file(assetId) ?: return null
        return runCatching { f.readBytes() }.getOrNull()?.takeIf { it.isNotEmpty() }
    }
}
