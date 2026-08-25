package com.smarthome.livingroom_v2.skill

import android.content.Context
import com.smarthome.livingroom_v2.brain.dto.ServiceDescriptor

data class SkillContext(
    val appContext: Context,
    val edgeId: String,
    val planId: String,
    val stepId: String,
)

data class SkillResult(
    val ok: Boolean,
    val message: String? = null,
    val outputs: Map<String, String> = emptyMap(),
) {
    companion object {
        fun ok(message: String? = null, outputs: Map<String, String> = emptyMap()) =
            SkillResult(ok = true, message = message, outputs = outputs)

        fun error(message: String) = SkillResult(ok = false, message = message)
    }
}

/**
 * Local executable service plugin.
 * Wire contract is [service]; invoke with [capabilityId] (not legacy action names).
 *
 * Runtime MUST call [isAvailable] before [execute]. Default: available.
 */
interface Skill {
    fun service(): ServiceDescriptor

    /**
     * Fast preflight. Default returns ok.
     * Override for hardware that can be probed cheaply (e.g. camera AP).
     */
    suspend fun isAvailable(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = SkillResult.ok("available")

    suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult
}
