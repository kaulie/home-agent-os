package com.smarthome.livingroom_android.command.dispatcher

import android.util.Log
import com.smarthome.livingroom_android.command.Task
import com.smarthome.livingroom_android.command.runtime.EdgeRuntime
import com.smarthome.livingroom_android.command.runtime.EdgeRuntimeNode
import com.smarthome.livingroom_android.command.runtime.TaskExecutionResult

interface TaskDispatcher {
    suspend fun dispatch(task: Task, node: EdgeRuntimeNode): TaskExecutionResult
}

class LocalTaskDispatcher(
    private val runtime: EdgeRuntime,
) : TaskDispatcher {
    override suspend fun dispatch(task: Task, node: EdgeRuntimeNode): TaskExecutionResult {
        Log.i(TAG, "dispatch taskId=${task.taskId} → node=${node.nodeId}")
        return runtime.execute(task, node)
    }

    companion object {
        private const val TAG = "TaskDispatcher"
    }
}
