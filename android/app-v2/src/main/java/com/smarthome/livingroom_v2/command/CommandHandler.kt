package com.smarthome.livingroom_v2.command

import android.util.Log
import com.smarthome.livingroom_v2.command.dispatcher.TaskDispatcher
import com.smarthome.livingroom_v2.command.runtime.EdgeRuntimeNode
import com.smarthome.livingroom_v2.command.runtime.TaskExecutionResult
import com.smarthome.livingroom_v2.command.scheduler.CronJobScheduler
import com.smarthome.livingroom_v2.command.scheduler.EventTriggerScheduler
import com.smarthome.livingroom_v2.command.scheduler.InstantScheduler
import com.smarthome.livingroom_v2.command.scheduler.TaskScheduler
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

class CommandHandler(
    private val dispatcher: TaskDispatcher,
    private val localNode: EdgeRuntimeNode,
    @Suppress("unused")
    private val intentStatusClient: IntentStatusClient? = null,
    private val instant: InstantScheduler = InstantScheduler(),
    private val cron: CronJobScheduler = CronJobScheduler(),
    private val event: EventTriggerScheduler = EventTriggerScheduler(),
    private val onLog: (String) -> Unit = {},
) {
    fun schedulerFor(spec: ScheduleSpec): TaskScheduler =
        when (spec) {
            is ScheduleSpec.Instant -> instant
            is ScheduleSpec.Cron -> cron
            is ScheduleSpec.Event -> event
        }

    suspend fun handle(commands: List<Command>): List<TaskExecutionResult> {
        if (commands.isEmpty()) return emptyList()
        val results = mutableListOf<TaskExecutionResult>()
        for (cmd in commands) {
            log("Command received id=${cmd.commandId} device=${cmd.device} action=${cmd.action} source=${cmd.source}")
            // Only server intents enter this handler; local debug actions bypass it.
            val tasks = CommandDecomposer.fromServerCommand(cmd)
            for (task in tasks) {
                log(
                    "Task decomposed taskId=${task.taskId} skill=${task.skillId} " +
                        "action=${task.action} schedule=${task.schedule.kind}",
                )
                val result = scheduleAndDispatch(task)
                results += result
            }
        }
        return results
    }

    private suspend fun scheduleAndDispatch(task: Task): TaskExecutionResult {
        val scheduler = schedulerFor(task.schedule)
        log("Scheduled(${task.schedule.kind}) taskId=${task.taskId}")
        return when (task.schedule) {
            is ScheduleSpec.Instant -> {
                val ready = awaitReady(scheduler, task)
                dispatchReady(ready)
            }
            is ScheduleSpec.Cron, is ScheduleSpec.Event -> {
                // Skeleton: register only; do not block tick waiting for trigger.
                scheduler.schedule(task) { /* onReady wired for future / debugFire */ }
                log(
                    "Task parked in ${task.schedule.kind} scheduler taskId=${task.taskId} " +
                        "(skeleton; use debugFire to run)",
                )
                TaskExecutionResult(
                    taskId = task.taskId,
                    ok = true,
                    message = "parked:${task.schedule.kind}",
                    skipped = true,
                )
            }
        }
    }

    private suspend fun awaitReady(scheduler: TaskScheduler, task: Task): Task =
        suspendCancellableCoroutine { cont ->
            scheduler.schedule(task) { ready ->
                if (cont.isActive) cont.resume(ready)
            }
        }

    private suspend fun dispatchReady(task: Task): TaskExecutionResult {
        // Cross-edge: IntentScheduler owns intent_scheduled/intent_dispatched;
        // IntentStepExecutor owns step_status 0/1/2/3 and running/succeeded/failed.
        log("Dispatched(local) taskId=${task.taskId} → ${localNode.nodeId}")
        val result = dispatcher.dispatch(task, localNode)
        val status = when {
            result.skipped -> "skipped"
            result.ok -> "ok"
            else -> "error"
        }
        log("Executed taskId=${task.taskId} action=${task.action} status=$status")
        val msg = result.message?.trim().orEmpty()
        if (msg.isNotEmpty()) {
            for (line in msg.lineSequence()) {
                val trimmed = line.trim()
                if (trimmed.isNotEmpty()) {
                    log("  └ $trimmed")
                }
            }
        }
        return result
    }

    private fun log(message: String) {
        Log.i(TAG, message)
        onLog(message)
    }

    companion object {
        private const val TAG = "CommandHandler"
    }
}
