package com.smarthome.livingroom_android.intent

import org.json.JSONObject
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.math.max

enum class IntentPhase(val wire: String, val rank: Int) {
    UPLOADED("intent_received", 0),
    INTENT_PARSED("intent_parsed", 1),
    SCHEDULED("intent_scheduled", 2),
    ASSIGNED("intent_dispatched", 3),
    RUNNING("running", 4),
    SUCCEEDED("succeeded", 5),
    FAILED("failed", 5),
    ;

    val isTerminal: Boolean get() = this == SUCCEEDED || this == FAILED

    val label: String get() = displayLabel(PhaseVisual.DONE)

    fun displayLabel(visual: PhaseVisual = PhaseVisual.DONE, reportedWire: IntentPhase? = null): String = when (this) {
        UPLOADED -> "已到达服务器"
        INTENT_PARSED -> {
            val waitingForParse = visual == PhaseVisual.ACTIVE &&
                (reportedWire == null || reportedWire == UPLOADED)
            if (waitingForParse) "意图解析中" else "意图解析完成，待下发到中控节点"
        }
        SCHEDULED -> "任务已调度"
        ASSIGNED -> "任务已分配到具体 edge"
        RUNNING -> "任务执行中"
        SUCCEEDED -> "任务执行完成（成功）"
        FAILED -> "任务执行完成（失败）"
    }

    companion object {
        val timelineOrder = listOf(
            UPLOADED, INTENT_PARSED, SCHEDULED, ASSIGNED, RUNNING, SUCCEEDED,
        )

        fun fromWire(raw: String?): IntentPhase? {
            val v = raw?.trim()?.lowercase().orEmpty()
            if (v.isEmpty()) return null
            return entries.firstOrNull { it.wire == v }
        }

        fun jobAccepted(intentId: String): Boolean {
            val id = intentId.trim()
            return id.isNotEmpty() && id != "pending…"
        }

        /** POST 200 with a real intent_id means intent_received already landed. */
        fun logisticsCurrent(wire: IntentPhase, intentId: String): IntentPhase {
            return if (wire == UPLOADED && jobAccepted(intentId)) INTENT_PARSED else wire
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
    val presentation: IntentPresentation? = null,
    val error: String? = null,
    val reportedWire: IntentPhase = IntentPhase.UPLOADED,
    /** POST accept / intent_base_time. Frozen across polls. */
    val acceptedAtMs: Long? = null,
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
            append(mark).append(' ').append(p.phase.displayLabel(p.visual, reportedWire))
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

        fun formatDualElapsed(clientMs: Long?, serverMs: Long?): String {
            val client = clientMs?.let { formatDuration(it) }
            val server = serverMs?.let { formatDuration(it) }
            return when {
                client != null && server != null -> "本机 $client · 服务 $server"
                client != null -> "本机 $client"
                server != null -> "服务 $server"
                else -> ""
            }
        }

        /**
         * First row completes at Brain accept (`intent_base_time`).
         * Parse wait is the second row, even while wire is still `intent_received`.
         */
        fun timeline(
            intentId: String,
            text: String,
            wire: IntentPhase,
            startedAtMs: Long,
            acceptedAtMs: Long? = null,
            nowMs: Long = System.currentTimeMillis(),
            planSteps: List<PlanStepRow> = emptyList(),
            presentation: IntentPresentation? = null,
            error: String? = null,
        ): IntentJourney {
            val logistics = IntentPhase.logisticsCurrent(wire, intentId)
            val accepted = when {
                acceptedAtMs != null -> acceptedAtMs
                IntentPhase.jobAccepted(intentId) -> nowMs
                else -> null
            }
            val entered = linkedMapOf<IntentPhase, Long>()
            entered[IntentPhase.UPLOADED] = startedAtMs
            if (IntentPhase.jobAccepted(intentId) && accepted != null) {
                entered[IntentPhase.INTENT_PARSED] = accepted
            }
            if (logistics.rank > IntentPhase.INTENT_PARSED.rank) {
                for (p in IntentPhase.timelineOrder) {
                    if (p.rank in 2..logistics.rank) {
                        entered.putIfAbsent(p, nowMs)
                    }
                }
            }
            val phases = IntentPhase.timelineOrder.map { p ->
                when {
                    logistics == IntentPhase.FAILED && p.rank == IntentPhase.SUCCEEDED.rank -> {
                        val failAt = entered[IntentPhase.FAILED] ?: nowMs
                        val prev = IntentPhase.timelineOrder.lastOrNull { it.rank < logistics.rank }
                        val prevAt = prev?.let { entered[it] }
                        PhaseRow(
                            phase = IntentPhase.FAILED,
                            visual = PhaseVisual.FAILED,
                            enteredAtMs = failAt,
                            durationMs = prevAt?.let { max(0L, failAt - it) }
                                ?: max(0L, nowMs - (entered[p] ?: startedAtMs)),
                        )
                    }
                    p.rank < logistics.rank -> {
                        val start = entered[p] ?: startedAtMs
                        val next = IntentPhase.timelineOrder.firstOrNull {
                            it.rank > p.rank && entered.containsKey(it)
                        } ?: logistics.takeIf { entered.containsKey(it) }
                        val end = next?.let { entered[it] } ?: nowMs
                        PhaseRow(
                            phase = p,
                            visual = PhaseVisual.DONE,
                            enteredAtMs = start,
                            durationMs = max(0L, end - start),
                        )
                    }
                    p.rank == logistics.rank -> {
                        val start = entered[p] ?: nowMs
                        val visual = if (logistics.isTerminal) PhaseVisual.DONE else PhaseVisual.ACTIVE
                        PhaseRow(
                            phase = p,
                            visual = visual,
                            enteredAtMs = start,
                            durationMs = max(0L, nowMs - start),
                        )
                    }
                    else -> PhaseRow(p, PhaseVisual.PENDING)
                }
            }
            return IntentJourney(
                intentId = intentId,
                text = text,
                phase = logistics,
                phases = phases,
                planSteps = planSteps,
                startedAtMs = startedAtMs,
                updatedAtMs = nowMs,
                presentation = presentation,
                error = error,
                reportedWire = wire,
                acceptedAtMs = accepted,
            )
        }
    }
}

data class IntentPresentation(
    val type: Kind,
    val channel: String = "",
    val endpoint: String = "",
    val from: String = "",
    val text: String = "",
    val videoUrl: String? = null,
    val assetId: String = "",
) {
    enum class Kind { TEXT, IMAGE, VIDEO, HTML, AUDIO }

    val hasContent: Boolean
        get() = when (type) {
            Kind.IMAGE -> assetId.isNotEmpty()
            Kind.VIDEO -> !videoUrl.isNullOrBlank()
            Kind.AUDIO -> !videoUrl.isNullOrBlank() || text.isNotEmpty()
            Kind.TEXT, Kind.HTML -> text.isNotEmpty()
        }

    val copyText: String
        get() = when {
            text.isNotEmpty() -> text
            !videoUrl.isNullOrBlank() -> videoUrl
            assetId.isNotEmpty() -> assetId
            else -> ""
        }

    companion object {
        fun parse(raw: Any?): IntentPresentation? {
            val obj = raw as? JSONObject ?: return null
            val typeRaw = obj.optString("type", "text").trim().lowercase()
            val type = when (typeRaw) {
                "image" -> Kind.IMAGE
                "video" -> Kind.VIDEO
                "html" -> Kind.HTML
                "audio" -> Kind.AUDIO
                else -> Kind.TEXT
            }
            val assetId = unwrapAssetId(
                when (val ref = obj.opt("asset_ref")) {
                    is JSONObject -> ref.optString("asset_id", "").trim()
                    is String -> ref.trim()
                    else -> ""
                }
            )
            val pres = IntentPresentation(
                type = type,
                channel = obj.optString("channel", "").trim(),
                endpoint = obj.optString("endpoint", "").trim(),
                from = obj.optString("from", "").trim(),
                text = obj.optString("text", "").trim(),
                videoUrl = obj.optString("video_url", "").trim().takeIf { it.isNotEmpty() },
                assetId = assetId,
            )
            return pres.takeIf { it.hasContent }
        }

        private fun unwrapAssetId(raw: String): String {
            val text = raw.trim()
            if (text.isEmpty() || !text.startsWith("{")) return text
            val inner = runCatching { JSONObject(text).optString("asset_id") }.getOrNull()
                ?.trim().orEmpty()
            return inner.ifEmpty { text }
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
        presentation: IntentPresentation? = active?.presentation,
        error: String? = active?.error,
    ) {
        val id = intentId.trim()
        if (id.isEmpty()) return
        val current = active
        val now = System.currentTimeMillis()
        val logistics = IntentPhase.logisticsCurrent(phase, id)

        if (current == null || current.intentId != id) {
            phaseEntered.clear()
        } else if (current.phase.isTerminal &&
            logistics.rank <= current.phase.rank &&
            logistics != IntentPhase.FAILED
        ) {
            return
        }

        val startedAt = current?.takeIf { it.intentId == id }?.startedAtMs ?: now
        if (IntentPhase.jobAccepted(id) && !phaseEntered.containsKey(IntentPhase.UPLOADED)) {
            phaseEntered[IntentPhase.UPLOADED] = startedAt
        }
        if (logistics.rank >= IntentPhase.INTENT_PARSED.rank &&
            !phaseEntered.containsKey(IntentPhase.INTENT_PARSED)
        ) {
            phaseEntered[IntentPhase.INTENT_PARSED] =
                current?.takeIf { it.intentId == id }?.acceptedAtMs ?: startedAt
        }

        // Record enter time for newly reached ranks
        val prevRank = current?.takeIf { it.intentId == id }?.phase?.rank ?: -1
        if (logistics.rank > prevRank || current?.intentId != id) {
            if (!phaseEntered.containsKey(logistics)) {
                phaseEntered[logistics] = now
            }
            for (p in IntentPhase.timelineOrder) {
                if (p.rank <= logistics.rank && !phaseEntered.containsKey(p)) {
                    phaseEntered[p] = if (p == IntentPhase.UPLOADED) startedAt else now
                }
            }
        } else if (!phaseEntered.containsKey(logistics)) {
            phaseEntered[logistics] = now
        }

        val phases = buildPhaseRows(logistics, now)
        val journey = IntentJourney(
            intentId = id,
            text = text.ifBlank { current?.text.orEmpty() },
            phase = logistics,
            phases = phases,
            planSteps = planSteps,
            startedAtMs = startedAt,
            updatedAtMs = now,
            presentation = presentation ?: current?.takeIf { it.intentId == id }?.presentation,
            error = error ?: current?.takeIf { it.intentId == id }?.error,
            reportedWire = phase,
            acceptedAtMs = current?.takeIf { it.intentId == id }?.acceptedAtMs
                ?: phaseEntered[IntentPhase.INTENT_PARSED],
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
