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
        version = "0.1.0",
        displayName = "Marshall WILLEN",
        group = "speaker",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.BLUETOOTH_CONNECT,
                description = "连接 Marshall 蓝牙音箱",
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
                description = "断开 Marshall 蓝牙音箱",
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
