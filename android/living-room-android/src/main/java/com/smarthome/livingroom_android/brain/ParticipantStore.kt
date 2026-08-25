package com.smarthome.livingroom_android.brain

import com.smarthome.livingroom_android.brain.dto.EndpointAd
import com.smarthome.livingroom_android.brain.dto.IntentSourceAd
import com.smarthome.livingroom_android.brain.dto.ParticipantWire
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.data.AppSettings

/** Identity + advertised roles / sources / endpoints for this Console node. */
class ParticipantStore(
    private val settings: AppSettings,
) {
    fun clientHint(): String = settings.clientHint

    fun enabledRoles(): List<String> = settings.enabledRoles

    fun setRole(role: String, enabled: Boolean) {
        if (role !in ParticipantWire.ALL_ROLES) return
        val next = settings.enabledRoles.toMutableSet()
        if (enabled) next.add(role) else next.remove(role)
        settings.enabledRoles = ParticipantWire.ordered(next)
    }

    fun intentSources(roles: List<String> = enabledRoles()): List<IntentSourceAd> {
        if (!roles.contains(ParticipantWire.ROLE_INTENT_SOURCE)) return emptyList()
        return listOf(
            IntentSourceAd(sourceId = "android.keyboard", channel = "text"),
            IntentSourceAd(sourceId = "android.microphone", channel = "voice"),
        )
    }

    fun endpoints(roles: List<String> = enabledRoles()): List<EndpointAd> {
        if (!roles.contains(ParticipantWire.ROLE_ENDPOINT)) return emptyList()
        return listOf(
            EndpointAd(
                endpointId = "android.display",
                type = "display",
                supportedPresentation = listOf("image", "text"),
            ),
        )
    }

    fun advertisedServices(
        roles: List<String> = enabledRoles(),
        installed: List<ServiceDescriptor>,
    ): List<ServiceDescriptor> {
        if (!roles.contains(ParticipantWire.ROLE_RUNTIME)) return emptyList()
        return installed
    }
}
