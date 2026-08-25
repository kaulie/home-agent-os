package com.smarthome.livingroom_android.scan

import android.content.Context
import java.io.File

/** Disk cache for local document-scan JPEGs (display only; capture stays in ScanCapture). */
object ScanPreviewStore {
    private const val FOLDER = "scan-previews"
    private const val MAX_FILES = 40

    fun save(context: Context, assetId: String, jpeg: ByteArray) {
        val aid = assetId.trim()
        if (aid.isEmpty() || jpeg.isEmpty()) return
        val dir = directory(context)
        dir.mkdirs()
        file(dir, aid).writeBytes(jpeg)
        prune(dir)
    }

    fun load(context: Context, assetId: String): ByteArray? {
        val aid = assetId.trim()
        if (aid.isEmpty()) return null
        val f = file(directory(context), aid)
        if (!f.isFile || f.length() == 0L) return null
        return runCatching { f.readBytes() }.getOrNull()
    }

    private fun directory(context: Context): File =
        File(context.applicationContext.filesDir, FOLDER)

    private fun file(dir: File, assetId: String): File {
        val safe = assetId.replace("/", "_")
        return File(dir, "$safe.jpg")
    }

    private fun prune(dir: File) {
        val ranked = dir.listFiles()?.filter { it.isFile }?.sortedByDescending { it.lastModified() }
            ?: return
        for (extra in ranked.drop(MAX_FILES)) {
            extra.delete()
        }
    }
}
