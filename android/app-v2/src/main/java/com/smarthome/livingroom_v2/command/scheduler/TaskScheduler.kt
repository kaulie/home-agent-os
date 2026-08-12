package com.smarthome.livingroom_v2.command.scheduler

import android.util.Log
import com.smarthome.livingroom_v2.command.ScheduleSpec
import com.smarthome.livingroom_v2.command.Task
import java.util.concurrent.ConcurrentHashMap

/** Base scheduler: decide when a task becomes ready for dispatch. */
abstract class TaskScheduler {
    protected data class Entry(
        val task: Task,
        val onReady: (Task) -> Unit,
    )

    protected val registry = ConcurrentHashMap<String, Entry>()

    abstract val kind: String

    open fun schedule(task: Task, onReady: (Task) -> Unit) {
        registry[task.taskId] = Entry(task, onReady)
        Log.i(TAG, "schedule kind=$kind taskId=${task.taskId} commandId=${task.commandId}")
        onScheduled(task, onReady)
    }

    fun cancel(taskId: String): Boolean {
        val removed = registry.remove(taskId) != null
        if (removed) Log.i(TAG, "cancel kind=$kind taskId=$taskId")
        return removed
    }

    fun listScheduled(): List<Task> = registry.values.map { it.task }

    /** Debug: fire a registered task's onReady (cron/event skeleton). */
    fun debugFire(taskId: String): Boolean {
        val entry = registry[taskId] ?: return false
        registry.remove(taskId)
        Log.i(TAG, "debugFire kind=$kind taskId=$taskId")
        entry.onReady(entry.task)
        return true
    }

    protected abstract fun onScheduled(task: Task, onReady: (Task) -> Unit)

    companion object {
        private const val TAG = "TaskScheduler"
    }
}

class InstantScheduler : TaskScheduler() {
    override val kind: String = ScheduleSpec.Instant.kind

    override fun onScheduled(task: Task, onReady: (Task) -> Unit) {
        registry.remove(task.taskId)
        onReady(task)
    }
}

/** Runnable skeleton: registers tasks; no cron parser yet. Use [debugFire] to trigger. */
class CronJobScheduler : TaskScheduler() {
    override val kind: String = "cron"

    override fun onScheduled(task: Task, onReady: (Task) -> Unit) {
        val expr = (task.schedule as? ScheduleSpec.Cron)?.expression ?: "?"
        Log.i(TAG, "cron registered taskId=${task.taskId} expr=$expr (skeleton, awaiting trigger)")
    }

    companion object {
        private const val TAG = "CronJobScheduler"
    }
}

/** Runnable skeleton: registers event waits; no event bus yet. Use [debugFire] to trigger. */
class EventTriggerScheduler : TaskScheduler() {
    override val kind: String = "event"

    override fun onScheduled(task: Task, onReady: (Task) -> Unit) {
        val ev = (task.schedule as? ScheduleSpec.Event)?.eventType ?: "?"
        Log.i(TAG, "event registered taskId=${task.taskId} event=$ev (skeleton, awaiting trigger)")
    }

    companion object {
        private const val TAG = "EventTriggerScheduler"
    }
}
