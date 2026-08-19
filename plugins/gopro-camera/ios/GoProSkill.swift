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
                    description: "能：用 GoPro 拍一张照片并上传，产出 capture_ref。用户要拍照时用本能力。不能：分析照片、投电视、TTS、无图硬答已经看了；产出 photo_url。",
                    outputSchema: [
                        "capture_ref": SchemaField(
                            type: "string",
                            required: true,
                            description: "AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url。"
                        ),
                    ]
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.takeVideo,
                    description: "能：开始 GoPro 录像。不能：当拍照（用 camera.capture）；分析画面；投屏。"
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
