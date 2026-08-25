package com.smarthome.livingroom_v2.skill.speaker

import android.util.Log
import com.smarthome.livingroom_v2.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_v2.brain.dto.SchemaField
import com.smarthome.livingroom_v2.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_v2.capability.Capabilities
import com.smarthome.livingroom_v2.skill.Skill
import com.smarthome.livingroom_v2.skill.SkillContext
import com.smarthome.livingroom_v2.skill.SkillResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Marshall WILLEN Bluetooth speaker.
 * Defined for wire/registry; Chromecast does not install this skill currently.
 */
class MarshallSpeakerSkill : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.4.0",
        displayName = "Marshall WILLEN",
        group = "speaker",
        capabilities = listOf(
            // Structured ads — aligned with mac capability_ads (bluetooth.*).
            CapabilityDescriptor(
                capabilityId = Capabilities.BLUETOOTH_CONNECT,
                role = "蓝牙音箱连接器",
                plannerRecognize = "把 Marshall 一类蓝牙音箱连上。只负责连接，不负责选歌播放",
                typicalTriggers = listOf("连上音箱", "连接音箱", "连上马歇尔"),
                doNotDispatch = listOf("放歌本身", "TTS", "开灯", "断开音箱"),
                kind = "action",
                inputSchema = mapOf(
                    "device_name" to SchemaField(
                        type = "string",
                        required = false,
                        description = "设备名",
                    ),
                ),
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.BLUETOOTH_DISCONNECT,
                role = "蓝牙音箱断开器",
                plannerRecognize = "断开已连接的蓝牙音箱。只负责断开，不负责停歌或放歌",
                typicalTriggers = listOf("断开音箱", "断开蓝牙", "断开马歇尔"),
                doNotDispatch = listOf("放歌本身", "TTS", "开灯", "连上音箱"),
                kind = "action",
                inputSchema = mapOf(
                    "device_name" to SchemaField(
                        type = "string",
                        required = false,
                        description = "设备名",
                    ),
                ),
            ),
        ),
    )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.IO) {
        Log.i(TAG, "execute capability=$capabilityId params=$params")
        val name = params["device_name"]?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?: BluetoothSpeakerConnector.DEFAULT_NAME
        val connector = BluetoothSpeakerConnector(ctx.appContext)
        when (capabilityId) {
            Capabilities.BLUETOOTH_CONNECT -> {
                val r = connector.connectBondedSpeaker(nameHint = name)
                if (r.success) SkillResult.ok(r.message) else SkillResult.error(r.message)
            }
            Capabilities.BLUETOOTH_DISCONNECT -> {
                val r = connector.disconnectBondedSpeaker(nameHint = name)
                if (r.success) SkillResult.ok(r.message) else SkillResult.error(r.message)
            }
            else -> SkillResult.error("unsupported capability: $capabilityId")
        }
    }

    companion object {
        const val SKILL_ID = "marshall.willen"
        private const val TAG = "MarshallSpeakerSkill"
    }
}
