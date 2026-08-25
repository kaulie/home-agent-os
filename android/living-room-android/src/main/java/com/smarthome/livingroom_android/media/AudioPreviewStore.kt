package com.smarthome.livingroom_android.media

import android.content.Context
import java.io.File

object AudioPreviewStore {
    private const val FOLDER = "audio-previews"
    private const val MAX_FILES = 40

    fun save(context: Context, assetId: String, bytes: ByteArray, ext: String = "m4a") {
        val aid = assetId.trim()
        if (aid.isEmpty() || bytes.isEmpty()) return
        val dir = directory(context)
        dir.mkdirs()
        file(dir, aid, ext).writeBytes(bytes)
        prune(dir)
    }

    fun loadFile(context: Context, assetId: String): File? {
        val aid = assetId.trim()
        if (aid.isEmpty()) return null
        val dir = directory(context)
        val hit = dir.listFiles()?.firstOrNull { it.nameWithoutExtension == aid.replace("/", "_") }
        return hit?.takeIf { it.isFile && it.length() > 0L }
    }

    private fun directory(context: Context): File =
        File(context.applicationContext.filesDir, FOLDER)

    private fun file(dir: File, assetId: String, ext: String): File {
        val safe = assetId.replace("/", "_")
        val suffix = ext.trim('.').ifEmpty { "m4a" }
        return File(dir, "$safe.$suffix")
    }

    private fun prune(dir: File) {
        val ranked = dir.listFiles()?.filter { it.isFile }?.sortedByDescending { it.lastModified() }
            ?: return
        for (extra in ranked.drop(MAX_FILES)) extra.delete()
    }
}
