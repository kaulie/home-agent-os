# RuntimeAgentSDK

Edge runtime façade for capability plugins. Plugins talk to external/business services through this SDK instead of owning HTTP details.

## Swift layout

```text
ios/
  RuntimeAgentSDK.swift
  EdgeRuntimeContext.swift
  Asset/
    AssetType.swift
    Asset.swift
    PhotoAsset.swift
  AssetManager/
    AssetManager.swift
    AssetHTTPTransport.swift
```

## Typical usage

```swift
let asset = PhotoAsset(location: localPath)
let published = try await RuntimeAgentSDK.edgeRuntimeContext.assets.publish(asset)

let latest = try await RuntimeAgentSDK.edgeRuntimeContext.assets.fetchLatest(type: .photo)
```

Business server URLs for photo upload / download-latest live inside `AssetHTTPTransport` (SDK-owned), not in App UI constants.

`publish` parses upload JSON for `saved_as` / `url`, then sets the public Cast URL to  
`http://115.190.153.53:8080/{saved_as}` (`AssetHTTPTransport.defaultPublicPhotoBaseURL`).  
Exposed via `AssetManager.lastPublishUrl` / `lastPublishSavedAs` (also sets `asset.id` to that URL).

HTTP timing uses SDK-local `RuntimeHTTP` (independent of App `TimedHTTP` and plugin `GoProHTTP`).
