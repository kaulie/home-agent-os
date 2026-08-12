package com.smarthome.livingroom_android.intent

import java.util.concurrent.CopyOnWriteArrayList
import kotlin.math.max

enum class IntentPhase(val wire: String, val label: String, val rank: Int) {
    UPLOADED("intent_received", "上传到服务器，待意图解析", 0),
    INTENT_PARSED("intent_parsed", "意图解析完成，待下发到中控节点", 1),
    SCHEDULED("intent_scheduled", "任务已调度", 2),
    ASSIGNED("intent_dispatched", "任务已分配到具体 edge", 3),
    RUNNING("running", "任务执行中", 4),
    SUCCEEDED("succeeded", "任务执行完成（成功）", 5),
    FAILED("failed", "任务执行完成（失败）", 5),
    ;

    val isTerminal: Boolean get() = this == SUCCEEDED || this == FAILED

    companion object {
        val timelineOrder = listOf(
            UPLOADED, INTENT_PARSED, SCHEDULED, ASSIGNED, RUNNING, SUCCEEDED,
        )

        fun fromWire(raw: String?): IntentPhase? {
            val v = raw?.trim()?.lowercase().orEmpty()
            if (v.isEmpty()) return null
            return entries.firstOrNull { it.wire == v }
        }
    }
}

enum class PhaseVisual { PENDING, ACTIVE, DONE, FAILED }

data class PhaseRow(
    val phase: IntentPhase,
    val visual: PhaseVisual,
    val detail: String = "",
    /** When this phase became active/done. */
    val enteredAtMs: Long? = null,
    /** Duration spent in this phase (ms). Null if still pending / unknown. */
    val durationMs: Long? = null,
)

data class PlanStepRow(
    val step: Int,
    val capability: String,
    val status: String,
    val detail: String = "",
    val startedAtMs: Long? = null,
    val finishedAtMs: Long? = null,
) {
    fun durationMs(nowMs: Long = System.currentTimeMillis()): Long? {
        val start = startedAtMs ?: return null
        val end = finishedAtMs ?: if (status == "running") nowMs else return null
        return max(0L, end - start)
    }
}

data class IntentJourney(
    val intentId: String,
    val text: String,
    val phase: IntentPhase,
    val phases: List<PhaseRow>,
    val planSteps: List<PlanStepRow>,
    val startedAtMs: Long = System.currentTimeMillis(),
    val updatedAtMs: Long = System.currentTimeMillis(),
) {
    fun logisticsText(nowMs: Long = System.currentTimeMillis()): String = buildString {
        append("意图 #").append(intentId)
        if (text.isNotBlank()) append(" · ").append(text.take(80))
        val total = max(0L, nowMs - startedAtMs)
        append(" · 总耗时 ").append(formatDuration(total))
        append('\n')
        for (p in phases) {
            val mark = when (p.visual) {
                PhaseVisual.DONE -> "✓"
                PhaseVisual.ACTIVE -> "▶"
                PhaseVisual.FAILED -> "✗"
                PhaseVisual.PENDING -> "·"
            }
            append(mark).append(' ').append(p.phase.label)
            val dur = when (p.visual) {
                PhaseVisual.ACTIVE -> p.enteredAtMs?.let { max(0L, nowMs - it) }
                PhaseVisual.DONE, PhaseVisual.FAILED -> p.durationMs
                PhaseVisual.PENDING -> null
            }
            if (dur != null) {
                append("  [").append(formatDuration(dur)).append(']')
            } else if (p.visual == PhaseVisual.PENDING) {
                append("  [—]")
            }
            if (p.detail.isNotBlank()) append(" — ").append(p.detail)
            append('\n')
        }
        if (planSteps.isNotEmpty()) {
            append("--- plan ---\n")
            for (s in planSteps) {
                append("step").append(s.step).append(' ').append(s.capability)
                    .append(" [").append(s.status).append(']')
                s.durationMs(nowMs)?.let { append("  ").append(formatDuration(it)) }
                if (s.detail.isNotBlank()) append(" ").append(s.detail)
                append('\n')
            }
        }
    }

    companion object {
        fun formatDuration(ms: Long): String =
            when {
                ms < 1000 -> "${ms}ms"
                ms < 60_000 -> {
                    val sec = ms / 1000.0
                    if (sec < 10) String.format("%.1fs", sec) else "${ms / 1000}s"
                }
                else -> {
                    val m = ms / 60_000
                    val s = (ms % 60_000) / 1000
                    "${m}m${s}s"
                }
            }
    }
}

class IntentJourneyStore {
    interface Listener {
        fun onJourneyChanged(journey: IntentJourney?)
    }

    private val listeners = CopyOnWriteArrayList<Listener>()

    /** phase wire/name → enteredAtMs */
    private val phaseEntered = linkedMapOf<IntentPhase, Long>()

    @Volatile
    var active: IntentJourney? = null
        private set

    fun addListener(l: Listener) {
        listeners += l
    }

    fun removeListener(l: Listener) {
        listeners -= l
    }

    fun upsert(
        intentId: String,
        text: String = active?.text.orEmpty(),
        phase: IntentPhase,
        planSteps: List<PlanStepRow> = active?.planSteps.orEmpty(),
    ) {
        val id = intentId.trim()
        if (id.isEmpty()) return
        val current = active
        val now = System.currentTimeMillis()

        if (current == null || current.intentId != id) {
            phaseEntered.clear()
        } else if (current.phase.isTerminal &&
            phase.rank <= current.phase.rank &&
            phase != IntentPhase.FAILED
        ) {
            return
        }

        // Record enter time for newly reached ranks
        val prevRank = current?.takeIf { it.intentId == id }?.phase?.rank ?: -1
        if (phase.rank > prevRank || current?.intentId != id) {
            // Close previous active phase duration implicitly via entered map
            if (!phaseEntered.containsKey(phase)) {
                phaseEntered[phase] = now
            }
            // Fill any skipped intermediate phases with same timestamp (0 duration)
            for (p in IntentPhase.timelineOrder) {
                if (p.rank <= phase.rank && !phaseEntered.containsKey(p)) {
                    phaseEntered[p] = now
                }
            }
        } else if (!phaseEntered.containsKey(phase)) {
            phaseEntered[phase] = now
        }

        val startedAt = current?.takeIf { it.intentId == id }?.startedAtMs ?: now
        val phases = buildPhaseRows(phase, now)
        val journey = IntentJourney(
            intentId = id,
            text = text.ifBlank { current?.text.orEmpty() },
            phase = phase,
            phases = phases,
            planSteps = planSteps,
            startedAtMs = startedAt,
            updatedAtMs = now,
        )
        active = journey
        listeners.forEach { it.onJourneyChanged(journey) }
    }

    fun updatePlanStep(capability: String, status: String, detail: String = "") {
        val cur = active ?: return
        val now = System.currentTimeMillis()
        val steps = cur.planSteps.toMutableList()
        val idx = steps.indexOfFirst { it.capability == capability }
        if (idx >= 0) {
            val old = steps[idx]
            val started = old.startedAtMs
                ?: if (status == "running" || status == "succeeded" || status == "failed") now else null
            val finished = when (status) {
                "succeeded", "failed", "skipped" -> old.finishedAtMs ?: now
                else -> null
            }
            steps[idx] = old.copy(
                status = status,
                detail = detail,
                startedAtMs = started,
                finishedAtMs = finished,
            )
        } else {
            val started = if (status != "waiting" && status != "queued") now else null
            val finished = if (status == "succeeded" || status == "failed" || status == "skipped") now else null
            steps += PlanStepRow(
                step = steps.size + 1,
                capability = capability,
                status = status,
                detail = detail,
                startedAtMs = started,
                finishedAtMs = finished,
            )
        }
        active = cur.copy(planSteps = steps, updatedAtMs = now)
        listeners.forEach { it.onJourneyChanged(active) }
    }

    /** Re-emit current journey so UI can refresh live elapsed times. */
    fun tick() {
        val j = active ?: return
        if (j.phase.isTerminal) return
        listeners.forEach { it.onJourneyChanged(j) }
    }

    fun clear() {
        phaseEntered.clear()
        active = null
        listeners.forEach { it.onJourneyChanged(null) }
    }

    private fun buildPhaseRows(current: IntentPhase, nowMs: Long): List<PhaseRow> {
        return IntentPhase.timelineOrder.map { p ->
            val entered = phaseEntered[p]
            when {
                current == IntentPhase.FAILED && p.rank == IntentPhase.SUCCEEDED.rank -> {
                    val failEntered = phaseEntered[IntentPhase.FAILED] ?: entered ?: nowMs
                    val prev = IntentPhase.timelineOrder.lastOrNull { it.rank < current.rank }
                    val prevEntered = prev?.let { phaseEntered[it] }
                    val dur = prevEntered?.let { max(0L, failEntered - it) }
                        ?: entered?.let { max(0L, nowMs - it) }
                    PhaseRow(
                        phase = IntentPhase.FAILED,
                        visual = PhaseVisual.FAILED,
                        enteredAtMs = failEntered,
                        durationMs = dur,
                    )
                }
                p.rank < current.rank -> {
                    val next = IntentPhase.timelineOrder.firstOrNull { it.rank > p.rank && phaseEntered.containsKey(it) }
                        ?: current.takeIf { phaseEntered.containsKey(it) }
                    val end = next?.let { phaseEntered[it] } ?: nowMs
                    val start = entered ?: end
                    PhaseRow(
                        phase = p,
                        visual = PhaseVisual.DONE,
                        enteredAtMs = start,
                        durationMs = max(0L, end - start),
                    )
                }
                p.rank == current.rank -> {
                    val start = entered ?: nowMs.also { phaseEntered[p] = it }
                    PhaseRow(
                        phase = p,
                        visual = PhaseVisual.ACTIVE,
                        enteredAtMs = start,
                        durationMs = max(0L, nowMs - start),
                    )
                }
                else -> PhaseRow(p, PhaseVisual.PENDING)
            }
        }
    }
}
