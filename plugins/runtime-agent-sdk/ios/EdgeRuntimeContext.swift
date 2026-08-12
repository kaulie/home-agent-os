import Foundation

/// Edge-side runtime context exposed to capability plugins.
final class EdgeRuntimeContext {
    let assets: AssetManager

    init(assets: AssetManager = AssetManager()) {
        self.assets = assets
    }
}
