package com.smarthome.livingroom_android.command

import org.json.JSONObject
import java.util.Calendar
import java.util.TimeZone
import java.util.regex.Pattern

/**
 * execution_timing + base_time protocol helpers (port of server/execution_timing.py).
 *
 * Times are Unix epoch milliseconds. Never emit delay_sec on the wire.
 */
data class ExecutionTiming(
    val mode: String,
    val execTime: Long? = null,
    val firstExecTime: Long? = null,
    val intervalSec: Int? = null,
    val cron: String? = null,
    val timezone: String? = null,
    val endTime: Long? = null,
    val count: Int? = null,
) {
    val isRecurring: Boolean
        get() = mode == ExecutionTimingGate.MODE_INTERVAL ||
            mode == ExecutionTimingGate.MODE_CRON
}

data class TimingGate(
    val due: Boolean,
    val skipBeat: Boolean,
    val terminal: Boolean,
    val reason: String,
    val plannedStart: Long? = null,
)

object ExecutionTimingGate {
    const val MODE_IMMEDIATE = "immediate"
    const val MODE_DELAY = "delay"
    const val MODE_INTERVAL = "interval"
    const val MODE_CRON = "cron"

    private const val ONE_SHOT_MISS_MS = 15L * 60L * 1000L
    private const val PERIODIC_MISS_CAP_MS = 15L * 60L * 1000L

    private val FIELD_RE = Pattern.compile(
        """^(\*|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)(?:/(\d+))?$""",
    )

    fun asMs(value: Any?): Long? {
        if (value == null || value is Boolean || value === JSONObject.NULL) return null
        val n = when (value) {
            is Number -> value.toLong()
            is String -> value.trim().toLongOrNull() ?: return null
            else -> return null
        }
        var ms = n
        // Accidental seconds → ms
        if (ms in 1 until 10_000_000_000L) ms *= 1000
        return if (ms > 0) ms else null
    }

    fun parseExecutionTiming(step: JSONObject?): ExecutionTiming {
        if (step == null) return ExecutionTiming(mode = MODE_IMMEDIATE)
        val raw = step.optJSONObject("execution_timing")
            ?: return ExecutionTiming(mode = MODE_IMMEDIATE)
        // Strip illegal wire field if present.
        raw.remove("delay_sec")
        raw.remove("delaySec")
        var mode = raw.optString("mode", MODE_IMMEDIATE).trim().lowercase()
        if (mode.isEmpty()) mode = MODE_IMMEDIATE
        if (mode !in setOf(MODE_IMMEDIATE, MODE_DELAY, MODE_INTERVAL, MODE_CRON)) {
            mode = MODE_IMMEDIATE
        }
        val intervalSec = when (val interval = raw.opt("interval_sec")) {
            null, JSONObject.NULL -> null
            is Number -> interval.toInt().takeIf { it > 0 }
            is String -> interval.trim().toIntOrNull()?.takeIf { it > 0 }
            else -> null
        }
        val count = when (val countRaw = raw.opt("count")) {
            null, JSONObject.NULL -> null
            is Number -> countRaw.toInt().takeIf { it > 0 }
            is String -> countRaw.trim().toIntOrNull()?.takeIf { it > 0 }
            else -> null
        }
        return ExecutionTiming(
            mode = mode,
            execTime = asMs(raw.opt("exec_time")),
            firstExecTime = asMs(raw.opt("first_exec_time")),
            intervalSec = intervalSec,
            cron = raw.optString("cron", "").trim().ifEmpty { null },
            timezone = raw.optString("timezone", "").trim().ifEmpty { null },
            endTime = asMs(raw.opt("end_time")),
            count = count,
        )
    }

    fun plannedStartMs(timing: ExecutionTiming, beatIndex: Int): Long? {
        if (beatIndex < 0) return null
        return when (timing.mode) {
            MODE_IMMEDIATE -> null
            MODE_DELAY -> timing.execTime
            MODE_INTERVAL -> {
                val first = timing.firstExecTime ?: return null
                val interval = timing.intervalSec ?: return null
                first + beatIndex.toLong() * interval.toLong() * 1000L
            }
            MODE_CRON -> {
                val first = timing.firstExecTime ?: return null
                if (beatIndex == 0) return first
                var t = first
                repeat(beatIndex) {
                    val nxt = cronNextAfter(timing.cron.orEmpty(), t, timing.timezone) ?: return null
                    t = nxt
                }
                t
            }
            else -> null
        }
    }

    fun nextPlannedAfter(timing: ExecutionTiming, plannedStart: Long): Long? =
        when (timing.mode) {
            MODE_INTERVAL -> {
                val interval = timing.intervalSec ?: return null
                plannedStart + interval.toLong() * 1000L
            }
            MODE_CRON -> cronNextAfter(timing.cron.orEmpty(), plannedStart, timing.timezone)
            else -> null
        }

    fun missWindowMs(timing: ExecutionTiming, plannedStart: Long): Long {
        if (timing.mode == MODE_IMMEDIATE || timing.mode == MODE_DELAY || !timing.isRecurring) {
            return ONE_SHOT_MISS_MS
        }
        val nxt = nextPlannedAfter(timing, plannedStart)
        if (nxt == null || nxt <= plannedStart) return PERIODIC_MISS_CAP_MS
        val half = maxOf(0L, (nxt - plannedStart) / 2)
        return minOf(half, PERIODIC_MISS_CAP_MS)
    }

    fun timingGate(
        timing: ExecutionTiming,
        nowMs: Long,
        beatIndex: Int = 0,
    ): TimingGate {
        if (timing.mode == MODE_IMMEDIATE) {
            return TimingGate(
                due = true,
                skipBeat = false,
                terminal = false,
                reason = "immediate",
            )
        }
        if (timing.count != null && beatIndex >= timing.count) {
            return TimingGate(
                due = false,
                skipBeat = false,
                terminal = true,
                reason = "count exhausted",
            )
        }
        val planned = plannedStartMs(timing, beatIndex)
            ?: return TimingGate(
                due = false,
                skipBeat = false,
                terminal = false,
                reason = "missing planned start",
            )
        if (timing.endTime != null && planned > timing.endTime) {
            return TimingGate(
                due = false,
                skipBeat = false,
                terminal = true,
                reason = "past end_time",
                plannedStart = planned,
            )
        }
        if (nowMs < planned) {
            return TimingGate(
                due = false,
                skipBeat = false,
                terminal = false,
                reason = "wait until $planned",
                plannedStart = planned,
            )
        }
        val late = nowMs - planned
        val window = missWindowMs(timing, planned)
        if (late > window) {
            return if (timing.isRecurring) {
                TimingGate(
                    due = false,
                    skipBeat = true,
                    terminal = false,
                    reason = "miss window exceeded ($late>$window)",
                    plannedStart = planned,
                )
            } else {
                TimingGate(
                    due = false,
                    skipBeat = false,
                    terminal = true,
                    reason = "one-shot expired ($late>$window)",
                    plannedStart = planned,
                )
            }
        }
        return TimingGate(
            due = true,
            skipBeat = false,
            terminal = false,
            reason = "due",
            plannedStart = planned,
        )
    }

    /** Next fire strictly after [afterMs] for standard 5-field cron (min hour dom mon dow). */
    fun cronNextAfter(expr: String, afterMs: Long, tzName: String? = null): Long? {
        val parts = expr.trim().split(Regex("\\s+"))
        if (parts.size != 5) return null
        val minutes: List<Int>
        val hours: List<Int>
        val doms: Set<Int>
        val months: Set<Int>
        val dows: Set<Int>
        try {
            minutes = parseCronField(parts[0], 0, 59).sorted()
            hours = parseCronField(parts[1], 0, 23).sorted()
            doms = parseCronField(parts[2], 1, 31)
            months = parseCronField(parts[3], 1, 12)
            dows = parseCronField(parts[4], 0, 6) // 0=Sunday
        } catch (_: IllegalArgumentException) {
            return null
        }
        if (minutes.isEmpty() || hours.isEmpty() || months.isEmpty()) return null

        val tz = resolveTz(tzName)
        val startCal = Calendar.getInstance(tz).apply {
            timeInMillis = afterMs
            add(Calendar.MINUTE, 1)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        val startMs = startCal.timeInMillis
        val domStar = parts[2] == "*" || parts[2].startsWith("*/")
        val dowStar = parts[4] == "*" || parts[4].startsWith("*/")

        val day = Calendar.getInstance(tz).apply {
            timeInMillis = startMs
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        repeat(400) {
            if (day.get(Calendar.MONTH) + 1 in months) {
                // Calendar: Sunday=1..Saturday=7 → cron: Sunday=0..Saturday=6
                val cronWd = day.get(Calendar.DAY_OF_WEEK) - 1
                val domOk = day.get(Calendar.DAY_OF_MONTH) in doms
                val dowOk = cronWd in dows
                val dayOk = when {
                    domStar && dowStar -> true
                    domStar -> dowOk
                    dowStar -> domOk
                    else -> domOk || dowOk
                }
                if (dayOk) {
                    for (hour in hours) {
                        for (minute in minutes) {
                            val cand = (day.clone() as Calendar).apply {
                                set(Calendar.HOUR_OF_DAY, hour)
                                set(Calendar.MINUTE, minute)
                                set(Calendar.SECOND, 0)
                                set(Calendar.MILLISECOND, 0)
                            }
                            if (cand.timeInMillis >= startMs) {
                                return cand.timeInMillis
                            }
                        }
                    }
                }
            }
            day.add(Calendar.DAY_OF_MONTH, 1)
        }
        return null
    }

    private fun resolveTz(name: String?): TimeZone {
        if (name.isNullOrBlank()) return TimeZone.getTimeZone("UTC")
        val tz = TimeZone.getTimeZone(name)
        // Unknown IDs become GMT — treat blank-id GMT as UTC fallback when name wasn't GMT/UTC.
        if (tz.id == "GMT" &&
            !name.equals("GMT", ignoreCase = true) &&
            !name.equals("UTC", ignoreCase = true)
        ) {
            return TimeZone.getTimeZone("UTC")
        }
        return tz
    }

    private fun parseCronField(field: String, minV: Int, maxV: Int): Set<Int> {
        val trimmed = field.trim()
        val m = FIELD_RE.matcher(trimmed)
        if (!m.matches()) throw IllegalArgumentException("bad cron field: $field")
        val base = m.group(1)!!
        val stepS = m.group(2)
        val step = stepS?.toIntOrNull() ?: 1
        if (step <= 0) throw IllegalArgumentException("cron step must be > 0")
        val values = mutableSetOf<Int>()
        if (base == "*") {
            values.addAll(minV..maxV)
        } else {
            for (part in base.split(",")) {
                if ("-" in part) {
                    val ab = part.split("-", limit = 2)
                    val a = ab[0].toInt()
                    val b = ab[1].toInt()
                    values.addAll(a..b)
                } else {
                    values.add(part.toInt())
                }
            }
        }
        var out = values.filter { it in minV..maxV && (it - minV) % step == 0 }.toSet()
        if (step > 1 && base != "*") {
            val ordered = values.sorted()
            if (ordered.isEmpty()) return emptySet()
            val start = ordered.first()
            out = values.filter { it in minV..maxV && (it - start) % step == 0 }.toSet()
        }
        return out
    }
}
