package com.smarthome.livingroom_v2.brain

import com.smarthome.livingroom_v2.brain.dto.EndpointAd
import com.smarthome.livingroom_v2.brain.dto.IntentSourceAd
import com.smarthome.livingroom_v2.brain.dto.ParticipantWire
import com.smarthome.livingroom_v2.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_v2.data.AppSettings

/** Identity + advertised roles / sources / endpoints for this Chromecast node. */
class ParticipantStore(
    private val settings: AppSettings,
) {
    fun enabledRoles(): List<String> = settings.enabledRoles

    fun intentSources(roles: List<String> = enabledRoles()): List<IntentSourceAd> {
        if (!roles.contains(ParticipantWire.ROLE_INTENT_SOURCE)) return emptyList()
        return emptyList()
    }

    fun endpoints(roles: List<String> = enabledRoles()): List<EndpointAd> {
        if (!roles.contains(ParticipantWire.ROLE_ENDPOINT)) return emptyList()
        return listOf(
            EndpointAd(
                endpointId = "chromecast.display",
                type = "display",
                supportedPresentation = listOf("image", "text", "video"),
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
