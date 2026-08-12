package com.smarthome.livingroom_v2.command

/** When / how a task should fire. */
sealed class ScheduleSpec {
    data object Instant : ScheduleSpec()

    data class Cron(val expression: String) : ScheduleSpec()

    data class Event(val eventType: String, val filter: String? = null) : ScheduleSpec()

    val kind: String
        get() = when (this) {
            is Instant -> "instant"
            is Cron -> "cron"
            is Event -> "event"
        }
}

enum class CommandSource {
    /** Pulled from server intents / execution_plan. */
    SERVER,
}

/**
 * Unified command from server JSON or local inject.
 * Server intents shape (expanded from execution_plan): device/action from capability,
 * params include `intent_id`. Legacy `{ id, action, device }` still accepted.
 */
data class Command(
    val commandId: String,
    val device: String,
    val action: String,
    val params: Map<String, Any?> = emptyMap(),
    val schedule: ScheduleSpec = ScheduleSpec.Instant,
    val source: CommandSource = CommandSource.SERVER,
    val raw: Map<String, Any?> = emptyMap(),
)

/** Decomposed schedulable unit. */
data class Task(
    val taskId: String,
    val commandId: String,
    val skillId: String?,
    val action: String,
    val params: Map<String, Any?> = emptyMap(),
    val schedule: ScheduleSpec = ScheduleSpec.Instant,
    val targetHint: String? = null,
    val skipReason: String? = null,
)
