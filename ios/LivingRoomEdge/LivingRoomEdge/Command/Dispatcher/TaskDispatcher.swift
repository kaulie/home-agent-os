import Foundation

@MainActor
protocol TaskDispatcher: AnyObject {
    func dispatch(task: EdgeTask, node: EdgeRuntimeNode) async -> TaskExecutionResult
}

@MainActor
final class LocalTaskDispatcher: TaskDispatcher {
    private let runtime: EdgeRuntime

    init(runtime: EdgeRuntime) {
        self.runtime = runtime
    }

    func dispatch(task: EdgeTask, node: EdgeRuntimeNode) async -> TaskExecutionResult {
        NSLog("[TaskDispatcher] dispatch taskId=%@ → %@", task.taskId, node.nodeId)
        return await runtime.execute(task: task, node: node)
    }
}
