package com.smarthome.livingroom_android.skill

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Runtime-private GoPro inbox. Plugins do not list this directory.
 * `{filesDir}/captures/inbox/{capture_id}.jpg` + `.json` sidecar.
 */
object CaptureStore {
    private val idRegex = Regex("^cap_[0-9a-f]{24}$")

    data class Ref(
        val captureId: String,
        val type: String = "image",
        val mimeType: String = "image/jpeg",
    ) {
        fun json(): Map<String, String> = mapOf(
            "capture_id" to captureId,
            "type" to type,
            "mime_type" to mimeType,
        )

        fun jsonString(): String = JSONObject()
            .put("capture_id", captureId)
            .put("type", type)
            .put("mime_type", mimeType)
            .toString()
    }

    class StoreException(message: String) : Exception(message)

    fun inboxDir(ctx: Context): File {
        val dir = File(ctx.filesDir, "captures/inbox")
        dir.mkdirs()
        return dir
    }

    fun put(ctx: Context, jpeg: ByteArray, originalName: String = "", source: String = "gopro"): Ref {
        if (jpeg.isEmpty()) throw StoreException("拍照失败：空图片。")
        val cid = "cap_" + randomHex(12)
        val inbox = inboxDir(ctx)
        File(inbox, "$cid.jpg").writeBytes(jpeg)
        val meta = JSONObject()
            .put("capture_id", cid)
            .put("created_at", isoNow())
            .put("source", source)
            .put("original_name", originalName)
            .put("sha256", sha256(jpeg))
            .put("uploaded_dests", JSONArray())
        File(inbox, "$cid.json").writeText(meta.toString(2))
        return Ref(cid)
    }

    fun readBytes(ctx: Context, captureId: String): ByteArray {
        val cid = requireId(captureId)
        val f = File(inboxDir(ctx), "$cid.jpg")
        if (!f.isFile || f.length() <= 0L) {
            throw StoreException("本机 inbox 没有 $cid")
        }
        val data = f.readBytes()
        if (data.isEmpty()) throw StoreException("本机 inbox 没有 $cid")
        return data
    }

    fun markUploaded(ctx: Context, captureId: String, dest: String) {
        val cid = requireId(captureId)
        val destName = dest.trim()
        if (destName.isEmpty()) return
        val sidecar = File(inboxDir(ctx), "$cid.json")
        val meta = if (sidecar.isFile) {
            runCatching { JSONObject(sidecar.readText()) }.getOrElse { JSONObject() }
        } else {
            JSONObject()
        }
        val dests = meta.optJSONArray("uploaded_dests") ?: JSONArray()
        var found = false
        for (i in 0 until dests.length()) {
            if (dests.optString(i) == destName) found = true
        }
        if (!found) dests.put(destName)
        meta.put("capture_id", cid)
        meta.put("uploaded_dests", dests)
        sidecar.writeText(meta.toString(2))
    }

    fun uniquePending(ctx: Context, dest: String): String {
        val destName = dest.trim()
        val inbox = inboxDir(ctx)
        val pending = mutableListOf<String>()
        val files = inbox.listFiles() ?: emptyArray()
        for (f in files) {
            if (f.extension.lowercase() != "json") continue
            val cid = f.nameWithoutExtension
            if (!idRegex.matches(cid)) continue
            val jpg = File(inbox, "$cid.jpg")
            if (!jpg.isFile) continue
            val meta = runCatching { JSONObject(f.readText()) }.getOrNull()
            val dests = meta?.optJSONArray("uploaded_dests")
            var already = false
            if (dests != null && destName.isNotEmpty()) {
                for (i in 0 until dests.length()) {
                    if (dests.optString(i) == destName) already = true
                }
            }
            if (already) continue
            pending.add(cid)
        }
        if (pending.isEmpty()) {
            throw StoreException("本机 inbox 没有待上传的 capture，请带 capture_id")
        }
        if (pending.size > 1) {
            throw StoreException("本机 inbox 有多条待上传，请带 capture_id")
        }
        return pending[0]
    }

    fun parseCaptureId(raw: Any?): String? {
        when (raw) {
            null -> return null
            is Map<*, *> -> {
                val cid = raw["capture_id"]?.toString()?.trim().orEmpty()
                return cid.takeIf { idRegex.matches(it) }
            }
            else -> {
                val text = raw.toString().trim()
                if (text.isEmpty() || text.startsWith("$")) return null
                if (text.startsWith("{")) {
                    val obj = runCatching { JSONObject(text) }.getOrNull() ?: return null
                    val cid = obj.optString("capture_id").trim()
                    return cid.takeIf { idRegex.matches(it) }
                }
                return text.takeIf { idRegex.matches(it) }
            }
        }
    }

    private fun requireId(raw: String): String {
        val cid = raw.trim()
        if (!idRegex.matches(cid)) throw StoreException("无效 capture_id：$raw")
        return cid
    }

    private fun sha256(data: ByteArray): String {
        val d = MessageDigest.getInstance("SHA-256").digest(data)
        return d.joinToString("") { "%02x".format(it) }
    }

    private fun randomHex(byteCount: Int): String {
        val bytes = ByteArray(byteCount)
        SecureRandom().nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private fun isoNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }
}
