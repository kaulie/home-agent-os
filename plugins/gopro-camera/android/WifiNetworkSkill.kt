package com.smarthome.plugin.gopro

import android.app.Activity
import android.util.Log
import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.data.AppSettings
import com.smarthome.livingroom_android.skill.Skill
import com.smarthome.livingroom_android.skill.SkillContext
import com.smarthome.livingroom_android.skill.SkillResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Join / leave a named Wi‑Fi (e.g. GoPro AP).
 * Join uses Specifier dialog (needs foreground [Activity]).
 * For status-bar switch, UI should use ACTION_WIFI_ADD_NETWORKS + confirm.
 */
class WifiNetworkSkill(
    private val onProgress: (String) -> Unit = {},
    private val homeProbeUrl: String = "http://192.168.3.8:8080/",
) : Skill {
    override fun service(): ServiceDescriptor =
        ServiceDescriptor(
            serviceId = SKILL_ID,
            version = "0.1.3",
            displayName = "Wi‑Fi Switch",
            group = "network",
            capabilities = listOf(
                CapabilityDescriptor(
                    capabilityId = Capabilities.WIFI_JOIN,
                    kind = "action",
                    role = "临时 Wi-Fi 调试连接器",
                    plannerRecognize = "调试用：把手机临时加入指定 SSID（例如 GoPro 热点）。不是连蓝牙音箱、不是拍照、不是日常上网，不要排进用户家务计划",
                    typicalTriggers = listOf("连上 GoPro 热点", "加入指定 SSID"),
                    doNotDispatch = listOf("作为计划逐步执行", "拍照本身", "放歌", "连蓝牙音箱", "开灯", "知识问答", "日常上网"),
                    description = "Join via Specifier dialog (process bind; may not change status bar)",
                    inputSchema = mapOf(
                        "ssid" to SchemaField("string", required = false),
                        "password" to SchemaField("string", required = false),
                    ),
                ),
                CapabilityDescriptor(
                    capabilityId = Capabilities.WIFI_LEAVE,
                    kind = "action",
                    role = "临时 Wi-Fi 调试断开器",
                    plannerRecognize = "调试用：离开临时 SSID，回到家里默认网络。不是停歌、不是断开蓝牙音箱，不要排进用户家务计划",
                    typicalTriggers = listOf("离开 GoPro 热点", "回到家里默认网络"),
                    doNotDispatch = listOf("作为计划逐步执行", "拍照本身", "放歌", "断开蓝牙音箱", "开灯", "知识问答"),
                    description = "Leave temporary Wi‑Fi and return to default network",
                ),
            ),
        )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult {
        val activity = params[ACTIVITY_EXTRA] as? Activity
        return executeWithActivity(capabilityId, params, ctx, activity)
    }

    suspend fun executeWithActivity(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
        activity: Activity?,
    ): SkillResult = withContext(Dispatchers.Main) {
        val settings = AppSettings(ctx.appContext)
        val wifi = GoProWifiCoordinator(ctx.appContext, homeProbeUrl)
        when (capabilityId) {
            Capabilities.WIFI_JOIN -> {
                val ssid = params["ssid"]?.toString()?.trim().orEmpty()
                    .ifBlank { settings.goproSsid.trim() }
                val password = params["password"]?.toString() ?: settings.goproPassword
                if (ssid.isEmpty()) {
                    return@withContext SkillResult.error("SSID 为空，请先填写并保存")
                }
                if (activity == null || activity.isFinishing) {
                    return@withContext SkillResult.error(
                        "需要前台 Activity 才能弹出系统 Wi‑Fi 连接面板",
                    )
                }
                try {
                    val joined = wifi.connectViaSpecifier(
                        activity = activity,
                        ssid = ssid,
                        password = password.ifBlank { null },
                        onProgress = ::progress,
                    )
                    val snap = joined.snapshot ?: wifi.primarySnapshot()
                    val statusBarOk = wifi.isConfirmedOnSsid(ssid, snap)
                    if (statusBarOk) {
                        SkillResult.ok("已加入「${snap.ssid}」bssid=${snap.bssid}")
                    } else {
                        // Honest: Specifier bind ≠ status-bar switch
                        SkillResult.ok(
                            "进程已绑定「${joined.boundSsid ?: ssid}」" +
                                "（状态栏仍是「${snap.ssid ?: "未知"}」，未改系统默认网。" +
                                "若要状态栏切换请用「用系统设置加入」）",
                        )
                    }
                } catch (t: Throwable) {
                    Log.e(TAG, "wifi.join failed", t)
                    val cur = runCatching { wifi.primarySnapshot().summary }.getOrNull()
                    SkillResult.error(
                        (t.message ?: t.javaClass.simpleName) + "｜$cur",
                    )
                }
            }
            Capabilities.WIFI_LEAVE -> {
                try {
                    progress("离开临时 Wi‑Fi，恢复默认网络…")
                    withContext(Dispatchers.IO) {
                        wifi.disconnectGoPro(bindHome = true)
                        wifi.waitUntilHomeReady(timeoutMs = 30_000L, onProgress = ::progress)
                    }
                    SkillResult.ok("已离开｜${wifi.primarySnapshot().summary}")
                } catch (t: Throwable) {
                    wifi.disconnectGoPro(bindHome = true)
                    SkillResult.ok("已解除绑定（回家探测：${t.message}）")
                }
            }
            else -> SkillResult.error("unsupported: $capabilityId")
        }
    }

    private fun progress(msg: String) {
        Log.i(TAG, msg)
        onProgress(msg)
    }

    companion object {
        const val SKILL_ID = "network.wifi"
        const val ACTIVITY_EXTRA = "__activity"
        private const val TAG = "WifiNetworkSkill"
    }
}
