import Foundation

/// GoPro camera service: group=camera; wire capabilities camera.capture / take_video.
/// Extra debug actions (status/upload/…) stay invokable locally but are not advertised.
final class GoProSkill: Skill {
    static let skillId = "gopro.camera"

    private let controller: GoProController

    init(controller: GoProController) {
        self.controller = controller
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.7.0",
            displayName: "GoPro Camera",
            group: "camera",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: Capabilities.cameraCapture,
                    description: Capabilities.describe(Capabilities.cameraCapture),
                    outputSchema: [
                        "photo_local_path": SchemaField(
                            type: "string",
                            required: false,
                            description: "本地照片路径"
                        ),
                        "photo_url": SchemaField(
                            type: "string",
                            required: true,
                            description: "服务器图片下载地址"
                        ),
                        "saved_as": SchemaField(
                            type: "string",
                            required: false,
                            description: "服务器侧文件名"
                        ),
                    ]
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.takeVideo,
                    description: Capabilities.describe(Capabilities.takeVideo)
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        let result: ControllerResult
        switch capabilityId {
        case Capabilities.cameraCapture, "capture_photo", "take_photo":
            result = await controller.capturePhotoPipeline()
        case Capabilities.takeVideo, "start_recording":
            result = await controller.startRecording()
        case "stop_recording":
            result = await controller.stopRecording()
        case "status":
            result = await controller.fetchStatus()
        case "latest_photo":
            let forceRaw = params["force"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
            let force = forceRaw == "true" || forceRaw == "1" || forceRaw == "yes"
            let fetch = await controller.fetchLatestPhoto(forceRedownload: force)
            result = fetch.controllerResult
        case "upload_photo":
            let local = params["local_path"]?.trimmingCharacters(in: .whitespacesAndNewlines)
            let path = (local?.isEmpty == false) ? local : nil
            result = await controller.uploadPhoto(localPath: path)
        case "download_latest_from_server":
            result = await controller.downloadLatestFromServer()
        default:
            return .error("unsupported capability: \(capabilityId)")
        }

        if result.ok {
            return .ok(result.message, outputs: result.outputs)
        }
        return .error(result.message)
    }
}
