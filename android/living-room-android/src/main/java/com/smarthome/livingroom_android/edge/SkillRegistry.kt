package com.smarthome.livingroom_android.edge

import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.skill.Skill

class SkillRegistry {
    private val skills = linkedMapOf<String, Skill>()

    fun register(skill: Skill) {
        val id = skill.service().serviceId
        skills[id] = skill
    }

    fun registerAll(vararg skills: Skill) {
        skills.forEach { register(it) }
    }

    fun get(serviceId: String): Skill? = skills[serviceId]

    /** Resolve skill that owns [capabilityId]. */
    fun findByCapability(capabilityId: String): Pair<Skill, ServiceDescriptor>? {
        val want = capabilityId.trim()
        if (want.isEmpty()) return null
        for (skill in skills.values) {
            val svc = skill.service()
            if (svc.capabilities.any { it.capabilityId == want }) {
                return skill to svc
            }
        }
        return null
    }

    fun services(): List<ServiceDescriptor> = skills.values.map { it.service() }

    fun all(): Collection<Skill> = skills.values
}
