package com.smarthome.plugin.chromecast

import android.content.Context
import android.util.Log
import androidx.mediarouter.media.MediaRouteSelector
import androidx.mediarouter.media.MediaRouter
import com.google.android.gms.cast.CastMediaControlIntent
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.cast.framework.CastSession
import com.google.android.gms.cast.framework.SessionManagerListener
import com.google.android.gms.common.api.Status
import com.smarthome.livingroom_android.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Cast Sender for custom receiver [BuildConfig.DEFAULT_CAST_RECEIVER_APP_ID].
 * Sends image URL on [IMAGE_NAMESPACE] (no loadMedia).
 */
class CastSessionController private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val castContext: CastContext by lazy { CastContext.getSharedInstance(appContext) }

    var onLog: ((String) -> Unit)? = null

    suspend fun launchCustomReceiver(timeoutMs: Long = 45_000L): Result<Unit> =
        withContext(Dispatchers.Main) {
            runCatching {
                ensureSession(timeoutMs)
                log("custom receiver session ready app=${BuildConfig.DEFAULT_CAST_RECEIVER_APP_ID}")
            }
        }

    suspend fun castPhoto(photoUrl: String, timeoutMs: Long = 60_000L): Result<Unit> =
        withContext(Dispatchers.Main) {
            runCatching {
                val url = photoUrl.trim()
                require(url.startsWith("http://") || url.startsWith("https://")) {
                    "photo_url must be http(s): $url"
                }
                ensureSession(timeoutMs)
                val session = castContext.sessionManager.currentCastSession
                    ?: error("no CastSession after ensureSession")
                sendImageUrl(session, url)
                log("sent $IMAGE_NAMESPACE {\"url\":\"$url\"}")
            }
        }

    fun endSession() {
        runCatching {
            castContext.sessionManager.endCurrentSession(true)
            log("endCurrentSession")
        }
    }

    private suspend fun ensureSession(timeoutMs: Long) {
        val current = castContext.sessionManager.currentCastSession
        if (current?.isConnected == true) {
            log("reusing CastSession device=${current.castDevice?.friendlyName}")
            return
        }

        val appId = BuildConfig.DEFAULT_CAST_RECEIVER_APP_ID
        val selector = MediaRouteSelector.Builder()
            .addControlCategory(CastMediaControlIntent.categoryForCast(appId))
            .build()
        val router = MediaRouter.getInstance(appContext)
        val callback = object : MediaRouter.Callback() {}
        router.addCallback(selector, callback, MediaRouter.CALLBACK_FLAG_REQUEST_DISCOVERY)
        log("MediaRouter discovery for app=$appId (max ${timeoutMs / 1000}s)")
        if (probeCastPort()) {
            log(
                "Cast port ${BuildConfig.DEFAULT_CAST_FALLBACK_HOST}:" +
                    "${BuildConfig.DEFAULT_CAST_FALLBACK_PORT} reachable",
            )
        }

        try {
            withTimeout(timeoutMs) {
                var waited = 0L
                while (true) {
                    val connected = castContext.sessionManager.currentCastSession?.isConnected == true
                    if (connected) return@withTimeout

                    val route = router.routes.firstOrNull { r ->
                        !r.isDefault && !r.isBluetooth && r.matchesSelector(selector)
                    }

                    if (route != null && route != router.selectedRoute) {
                        log("selectRoute → ${route.name}")
                        awaitSessionAfterSelect(router, route, (timeoutMs - waited).coerceAtLeast(8_000L))
                        return@withTimeout
                    }
                    delay(500)
                    waited += 500
                }
            }
        } finally {
            router.removeCallback(callback)
        }

        castContext.sessionManager.currentCastSession?.takeIf { it.isConnected }
            ?: error(
                "Cast session not established. Open system Cast / ensure Chromecast on same Wi‑Fi. " +
                    "fallback=${BuildConfig.DEFAULT_CAST_FALLBACK_HOST}",
            )
    }

    private suspend fun awaitSessionAfterSelect(
        router: MediaRouter,
        route: MediaRouter.RouteInfo,
        timeoutMs: Long,
    ) {
        val sm = castContext.sessionManager
        withTimeout(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                val listener = object : SessionManagerListener<CastSession> {
                    override fun onSessionStarted(session: CastSession, sessionId: String) {
                        sm.removeSessionManagerListener(this, CastSession::class.java)
                        if (cont.isActive) cont.resume(Unit)
                    }

                    override fun onSessionStartFailed(session: CastSession, error: Int) {
                        sm.removeSessionManagerListener(this, CastSession::class.java)
                        if (cont.isActive) {
                            cont.resumeWithException(
                                IllegalStateException("session start failed code=$error route=${route.name}"),
                            )
                        }
                    }

                    override fun onSessionEnded(session: CastSession, error: Int) {}
                    override fun onSessionResumed(session: CastSession, wasSuspended: Boolean) {
                        sm.removeSessionManagerListener(this, CastSession::class.java)
                        if (cont.isActive) cont.resume(Unit)
                    }

                    override fun onSessionResumeFailed(session: CastSession, error: Int) {}
                    override fun onSessionSuspended(session: CastSession, reason: Int) {}
                    override fun onSessionStarting(session: CastSession) {}
                    override fun onSessionEnding(session: CastSession) {}
                    override fun onSessionResuming(session: CastSession, sessionId: String) {}
                }
                sm.addSessionManagerListener(listener, CastSession::class.java)
                router.selectRoute(route)
                cont.invokeOnCancellation {
                    sm.removeSessionManagerListener(listener, CastSession::class.java)
                }
            }
        }
    }

    private suspend fun sendImageUrl(session: CastSession, url: String) {
        val commandId = "cmd_" + java.util.UUID.randomUUID().toString().replace("-", "").take(16)
        val presentationId = "p_" + java.util.UUID.randomUUID().toString().replace("-", "").take(16)
        val asset = JSONObject()
            .put(
                "access",
                JSONObject().put("url", url).put("expires_at", 0),
            )
        val content = JSONObject().put("type", "image").put("asset", asset)
        val payloadObj = JSONObject()
            .put("presentation_id", presentationId)
            .put("content", content)
            .put("options", JSONObject().put("fit", "contain").put("background", "black"))
        val message = JSONObject()
            .put("type", "command")
            .put("protocol_version", 1)
            .put("command_id", commandId)
            .put("action", "present")
            .put("payload", payloadObj)
            .put("url", url) // legacy dual-write for old Receiver HTML
            .toString()
        suspendCancellableCoroutine { cont ->
            try {
                session.sendMessage(IMAGE_NAMESPACE, message)
                    .setResultCallback { status: Status ->
                        if (status.isSuccess) {
                            if (cont.isActive) cont.resume(Unit)
                        } else if (cont.isActive) {
                            cont.resumeWithException(IllegalStateException("sendMessage failed: $status"))
                        }
                    }
            } catch (t: Throwable) {
                if (cont.isActive) cont.resumeWithException(t)
            }
        }
        log("sent $IMAGE_NAMESPACE command_id=$commandId presentation_id=$presentationId (V1+url dual-write)")
        delay(200)
    }

    private fun probeCastPort(): Boolean =
        try {
            Socket().use { s ->
                s.connect(
                    InetSocketAddress(
                        BuildConfig.DEFAULT_CAST_FALLBACK_HOST,
                        BuildConfig.DEFAULT_CAST_FALLBACK_PORT,
                    ),
                    1500,
                )
            }
            true
        } catch (_: Throwable) {
            false
        }

    private fun log(msg: String) {
        Log.i(TAG, msg)
        onLog?.invoke(msg)
    }

    companion object {
        const val IMAGE_NAMESPACE = "urn:x-cast:local.image"
        private const val TAG = "CastSession"

        @Volatile
        private var instance: CastSessionController? = null

        fun get(context: Context): CastSessionController =
            instance ?: synchronized(this) {
                instance ?: CastSessionController(context.applicationContext).also { instance = it }
            }
    }
}
