#!/usr/bin/env python3
"""Generate a minimal Xcode project for LivingRoomEdge.

Includes:
  - ios/LivingRoomEdge/LivingRoomEdge/**/*.swift
  - plugins/gopro-camera/ios/*.swift
  - plugins/netease-music/ios/*.swift
  - plugins/chromecast-display/ios/*.swift
  - plugins/runtime-agent-sdk/ios/**/*.swift
  - SPM: SRGSSR/google-cast-sdk → GoogleCast
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "LivingRoomEdge"
REPO = ROOT.parent.parent
PLUGIN_GOPRO_IOS = REPO / "plugins" / "gopro-camera" / "ios"
PLUGIN_NETEASE_IOS = REPO / "plugins" / "netease-music" / "ios"
PLUGIN_CHROMECAST_IOS = REPO / "plugins" / "chromecast-display" / "ios"
RUNTIME_SDK_IOS = REPO / "plugins" / "runtime-agent-sdk" / "ios"
PROJ = ROOT / "LivingRoomEdge.xcodeproj"

CAST_SPM_URL = "https://github.com/SRGSSR/google-cast-sdk"
CAST_SPM_PRODUCT = "GoogleCast"
CAST_SPM_VERSION = "4.8.4"


def xid() -> str:
    return uuid.uuid4().hex[:24].upper()


@dataclass(frozen=True)
class SwiftFile:
    path: Path
    """Logical group path under the LivingRoomEdge src tree, or Plugins/... for plugins."""
    group_path: str
    """Display / path leaf name."""
    name: str
    """If set, PBXFileReference uses this path + SOURCE_ROOT (plugin files outside SRC)."""
    source_root_path: str | None = None


def collect_swift() -> list[SwiftFile]:
    files: list[SwiftFile] = []
    for f in sorted(SRC.rglob("*.swift")):
        rel = f.relative_to(SRC)
        parent = "" if str(rel.parent) == "." else str(rel.parent)
        files.append(SwiftFile(path=f, group_path=parent, name=f.name))
    if PLUGIN_GOPRO_IOS.is_dir():
        for f in sorted(PLUGIN_GOPRO_IOS.glob("*.swift")):
            rel_from_proj = Path("../../plugins/gopro-camera/ios") / f.name
            files.append(
                SwiftFile(
                    path=f,
                    group_path="Plugins/gopro-camera",
                    name=f.name,
                    source_root_path=str(rel_from_proj).replace("\\", "/"),
                )
            )
    if PLUGIN_NETEASE_IOS.is_dir():
        for f in sorted(PLUGIN_NETEASE_IOS.glob("*.swift")):
            rel_from_proj = Path("../../plugins/netease-music/ios") / f.name
            files.append(
                SwiftFile(
                    path=f,
                    group_path="Plugins/netease-music",
                    name=f.name,
                    source_root_path=str(rel_from_proj).replace("\\", "/"),
                )
            )
    if PLUGIN_CHROMECAST_IOS.is_dir():
        for f in sorted(PLUGIN_CHROMECAST_IOS.glob("*.swift")):
            rel_from_proj = Path("../../plugins/chromecast-display/ios") / f.name
            files.append(
                SwiftFile(
                    path=f,
                    group_path="Plugins/chromecast-display",
                    name=f.name,
                    source_root_path=str(rel_from_proj).replace("\\", "/"),
                )
            )
    if RUNTIME_SDK_IOS.is_dir():
        for f in sorted(RUNTIME_SDK_IOS.rglob("*.swift")):
            rel = f.relative_to(RUNTIME_SDK_IOS)
            parent = "" if str(rel.parent) == "." else str(rel.parent)
            group = "Plugins/runtime-agent-sdk" + (f"/{parent}" if parent else "")
            rel_from_proj = Path("../../plugins/runtime-agent-sdk/ios") / rel
            files.append(
                SwiftFile(
                    path=f,
                    group_path=group,
                    name=f.name,
                    source_root_path=str(rel_from_proj).replace("\\", "/"),
                )
            )
    return files


def main() -> None:
    files = collect_swift()
    info_plist = SRC / "Info.plist"

    project_id = xid()
    target_id = xid()
    sources_phase = xid()
    resources_phase = xid()
    frameworks_phase = xid()
    product_ref = xid()
    main_group = xid()
    products_group = xid()
    src_group = xid()
    sources_build_config_debug = xid()
    sources_build_config_release = xid()
    project_config_debug = xid()
    project_config_release = xid()
    target_config_list = xid()
    project_config_list = xid()

    # SPM: Google Cast
    spm_ref = xid()
    spm_product_dep = xid()
    spm_product_build = xid()

    file_refs: dict[SwiftFile, str] = {}
    build_files: dict[SwiftFile, str] = {}
    for f in files:
        file_refs[f] = xid()
        build_files[f] = xid()
    info_ref = xid()

    # Group hierarchy: SRC groups + Plugins/gopro-camera
    group_ids: dict[str, str] = {"": src_group}
    for f in files:
        parts = list(Path(f.group_path).parts) if f.group_path else []
        path = ""
        for part in parts:
            path = f"{path}/{part}" if path else part
            if path not in group_ids:
                group_ids[path] = xid()

    def group_children(group_path: str) -> list[str]:
        out: list[str] = []
        for g, gid in sorted(group_ids.items()):
            if g == "" or g == group_path:
                continue
            parent = "/".join(g.split("/")[:-1]) if "/" in g else ""
            if parent == group_path:
                out.append(gid)
        for f, fid in sorted(file_refs.items(), key=lambda x: x[0].name):
            if f.group_path == group_path:
                out.append(fid)
        if group_path == "" and info_plist.exists():
            out.append(info_ref)
        return out

    lines: list[str] = []
    lines.append("// !$*UTF8*$!")
    lines.append("{")
    lines.append("\tarchiveVersion = 1;")
    lines.append("\tclasses = {};")
    lines.append("\tobjectVersion = 56;")
    lines.append("\tobjects = {")
    lines.append("")

    # PBXBuildFile
    lines.append("/* Begin PBXBuildFile section */")
    for f, bid in build_files.items():
        lines.append(
            f"\t\t{bid} /* {f.name} in Sources */ = {{isa = PBXBuildFile; fileRef = {file_refs[f]} /* {f.name} */; }};"
        )
    lines.append(
        f"\t\t{spm_product_build} /* {CAST_SPM_PRODUCT} in Frameworks */ = {{isa = PBXBuildFile; productRef = {spm_product_dep} /* {CAST_SPM_PRODUCT} */; }};"
    )
    lines.append("/* End PBXBuildFile section */")
    lines.append("")

    # PBXFileReference
    lines.append("/* Begin PBXFileReference section */")
    lines.append(
        f"\t\t{product_ref} /* LivingRoomEdge.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = LivingRoomEdge.app; sourceTree = BUILT_PRODUCTS_DIR; }};"
    )
    for f, fid in file_refs.items():
        if f.source_root_path:
            lines.append(
                f"\t\t{fid} /* {f.name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = {f.name}; path = {f.source_root_path}; sourceTree = SOURCE_ROOT; }};"
            )
        else:
            lines.append(
                f"\t\t{fid} /* {f.name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {f.name}; sourceTree = \"<group>\"; }};"
            )
    lines.append(
        f"\t\t{info_ref} /* Info.plist */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = \"<group>\"; }};"
    )
    lines.append("/* End PBXFileReference section */")
    lines.append("")

    # PBXFrameworksBuildPhase
    lines.append("/* Begin PBXFrameworksBuildPhase section */")
    lines.append(f"\t\t{frameworks_phase} /* Frameworks */ = {{")
    lines.append("\t\t\tisa = PBXFrameworksBuildPhase;")
    lines.append("\t\t\tbuildActionMask = 2147483647;")
    lines.append("\t\t\tfiles = (")
    lines.append(f"\t\t\t\t{spm_product_build} /* {CAST_SPM_PRODUCT} in Frameworks */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    lines.append("\t\t};")
    lines.append("/* End PBXFrameworksBuildPhase section */")
    lines.append("")

    # PBXGroup
    lines.append("/* Begin PBXGroup section */")
    lines.append(f"\t\t{main_group} = {{")
    lines.append("\t\t\tisa = PBXGroup;")
    lines.append("\t\t\tchildren = (")
    lines.append(f"\t\t\t\t{src_group} /* LivingRoomEdge */,")
    lines.append(f"\t\t\t\t{products_group} /* Products */,")
    lines.append("\t\t\t);")
    lines.append('\t\t\tsourceTree = "<group>";')
    lines.append("\t\t};")
    lines.append(f"\t\t{products_group} /* Products */ = {{")
    lines.append("\t\t\tisa = PBXGroup;")
    lines.append("\t\t\tchildren = (")
    lines.append(f"\t\t\t\t{product_ref} /* LivingRoomEdge.app */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tname = Products;")
    lines.append('\t\t\tsourceTree = "<group>";')
    lines.append("\t\t};")

    for gpath, gid in group_ids.items():
        name = gpath.split("/")[-1] if gpath else "LivingRoomEdge"
        lines.append(f"\t\t{gid} /* {name} */ = {{")
        lines.append("\t\t\tisa = PBXGroup;")
        lines.append("\t\t\tchildren = (")
        for cid in group_children(gpath):
            lines.append(f"\t\t\t\t{cid},")
        lines.append("\t\t\t);")
        if gpath == "":
            lines.append("\t\t\tpath = LivingRoomEdge;")
        elif gpath.startswith("Plugins"):
            # Virtual group; file refs use SOURCE_ROOT paths
            lines.append(f"\t\t\tname = {name};")
        else:
            lines.append(f"\t\t\tpath = {name};")
        lines.append('\t\t\tsourceTree = "<group>";')
        lines.append("\t\t};")
    lines.append("/* End PBXGroup section */")
    lines.append("")

    # PBXNativeTarget
    lines.append("/* Begin PBXNativeTarget section */")
    lines.append(f"\t\t{target_id} /* LivingRoomEdge */ = {{")
    lines.append("\t\t\tisa = PBXNativeTarget;")
    lines.append(
        f"\t\t\tbuildConfigurationList = {target_config_list} /* Build configuration list for PBXNativeTarget \"LivingRoomEdge\" */;"
    )
    lines.append("\t\t\tbuildPhases = (")
    lines.append(f"\t\t\t\t{sources_phase} /* Sources */,")
    lines.append(f"\t\t\t\t{frameworks_phase} /* Frameworks */,")
    lines.append(f"\t\t\t\t{resources_phase} /* Resources */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tbuildRules = (")
    lines.append("\t\t\t);")
    lines.append("\t\t\tdependencies = (")
    lines.append("\t\t\t);")
    lines.append("\t\t\tname = LivingRoomEdge;")
    lines.append("\t\t\tpackageProductDependencies = (")
    lines.append(f"\t\t\t\t{spm_product_dep} /* {CAST_SPM_PRODUCT} */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tproductName = LivingRoomEdge;")
    lines.append(f"\t\t\tproductReference = {product_ref} /* LivingRoomEdge.app */;")
    lines.append('\t\t\tproductType = "com.apple.product-type.application";')
    lines.append("\t\t};")
    lines.append("/* End PBXNativeTarget section */")
    lines.append("")

    # PBXProject
    lines.append("/* Begin PBXProject section */")
    lines.append(f"\t\t{project_id} /* Project object */ = {{")
    lines.append("\t\t\tisa = PBXProject;")
    lines.append("\t\t\tattributes = {")
    lines.append("\t\t\t\tBuildIndependentTargetsInParallel = 1;")
    lines.append("\t\t\t\tLastSwiftUpdateCheck = 1500;")
    lines.append("\t\t\t\tLastUpgradeCheck = 1500;")
    lines.append("\t\t\t};")
    lines.append(
        f"\t\t\tbuildConfigurationList = {project_config_list} /* Build configuration list for PBXProject \"LivingRoomEdge\" */;"
    )
    lines.append('\t\t\tcompatibilityVersion = "Xcode 14.0";')
    lines.append("\t\t\tdevelopmentRegion = en;")
    lines.append("\t\t\thasScannedForEncodings = 0;")
    lines.append("\t\t\tknownRegions = (")
    lines.append("\t\t\t\ten,")
    lines.append("\t\t\t\tBase,")
    lines.append("\t\t\t);")
    lines.append(f"\t\t\tmainGroup = {main_group};")
    lines.append("\t\t\tpackageReferences = (")
    lines.append(f"\t\t\t\t{spm_ref} /* XCRemoteSwiftPackageReference \"google-cast-sdk\" */,")
    lines.append("\t\t\t);")
    lines.append(f"\t\t\tproductRefGroup = {products_group} /* Products */;")
    lines.append('\t\t\tprojectDirPath = "";')
    lines.append('\t\t\tprojectRoot = "";')
    lines.append("\t\t\ttargets = (")
    lines.append(f"\t\t\t\t{target_id} /* LivingRoomEdge */,")
    lines.append("\t\t\t);")
    lines.append("\t\t};")
    lines.append("/* End PBXProject section */")
    lines.append("")

    # Resources (empty)
    lines.append("/* Begin PBXResourcesBuildPhase section */")
    lines.append(f"\t\t{resources_phase} /* Resources */ = {{")
    lines.append("\t\t\tisa = PBXResourcesBuildPhase;")
    lines.append("\t\t\tbuildActionMask = 2147483647;")
    lines.append("\t\t\tfiles = (")
    lines.append("\t\t\t);")
    lines.append("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    lines.append("\t\t};")
    lines.append("/* End PBXResourcesBuildPhase section */")
    lines.append("")

    # Sources
    lines.append("/* Begin PBXSourcesBuildPhase section */")
    lines.append(f"\t\t{sources_phase} /* Sources */ = {{")
    lines.append("\t\t\tisa = PBXSourcesBuildPhase;")
    lines.append("\t\t\tbuildActionMask = 2147483647;")
    lines.append("\t\t\tfiles = (")
    for f, bid in build_files.items():
        lines.append(f"\t\t\t\t{bid} /* {f.name} in Sources */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    lines.append("\t\t};")
    lines.append("/* End PBXSourcesBuildPhase section */")
    lines.append("")

    # XCBuildConfiguration
    lines.append("/* Begin XCBuildConfiguration section */")
    for cfg_id, name in [(project_config_debug, "Debug"), (project_config_release, "Release")]:
        lines.append(f"\t\t{cfg_id} /* {name} */ = {{")
        lines.append("\t\t\tisa = XCBuildConfiguration;")
        lines.append("\t\t\tbuildSettings = {")
        lines.append("\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;")
        lines.append("\t\t\t\tCLANG_ENABLE_MODULES = YES;")
        lines.append("\t\t\t\tCLANG_ENABLE_OBJC_ARC = YES;")
        lines.append("\t\t\t\tCOPY_PHASE_STRIP = NO;")
        lines.append(
            f'\t\t\t\tDEBUG_INFORMATION_FORMAT = "{"dwarf" if name == "Debug" else "dwarf-with-dsym"}";'
        )
        if name == "Debug":
            lines.append("\t\t\t\tGCC_DYNAMIC_NO_PIC = NO;")
            lines.append("\t\t\t\tGCC_OPTIMIZATION_LEVEL = 0;")
            lines.append("\t\t\t\tONLY_ACTIVE_ARCH = YES;")
            lines.append("\t\t\t\tSWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;")
            lines.append('\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Onone";')
        lines.append("\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = 16.0;")
        lines.append("\t\t\t\tSDKROOT = iphoneos;")
        lines.append("\t\t\t\tSWIFT_VERSION = 5.0;")
        lines.append("\t\t\t};")
        lines.append(f"\t\t\tname = {name};")
        lines.append("\t\t};")

    for cfg_id, name in [(sources_build_config_debug, "Debug"), (sources_build_config_release, "Release")]:
        lines.append(f"\t\t{cfg_id} /* {name} */ = {{")
        lines.append("\t\t\tisa = XCBuildConfiguration;")
        lines.append("\t\t\tbuildSettings = {")
        lines.append("\t\t\t\tCODE_SIGN_ENTITLEMENTS = LivingRoomEdge/LivingRoomEdge.entitlements;")
        lines.append("\t\t\t\tCODE_SIGN_STYLE = Automatic;")
        lines.append("\t\t\t\tCURRENT_PROJECT_VERSION = 1;")
        lines.append('\t\t\t\tDEVELOPMENT_TEAM = "";')
        lines.append("\t\t\t\tENABLE_PREVIEWS = YES;")
        lines.append("\t\t\t\tGENERATE_INFOPLIST_FILE = NO;")
        lines.append("\t\t\t\tINFOPLIST_FILE = LivingRoomEdge/Info.plist;")
        lines.append("\t\t\t\tLD_RUNPATH_SEARCH_PATHS = (")
        lines.append('\t\t\t\t\t"$(inherited)",')
        lines.append('\t\t\t\t\t"@executable_path/Frameworks",')
        lines.append("\t\t\t\t);")
        lines.append("\t\t\t\tMARKETING_VERSION = 0.1.0;")
        lines.append("\t\t\t\tOTHER_LDFLAGS = (")
        lines.append('\t\t\t\t\t"$(inherited)",')
        lines.append('\t\t\t\t\t"-ObjC",')
        lines.append("\t\t\t\t);")
        lines.append("\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = com.gaolei.livingroom.edge.iphone;")
        lines.append('\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";')
        lines.append('\t\t\t\tSUPPORTED_PLATFORMS = "iphoneos iphonesimulator";')
        lines.append("\t\t\t\tSUPPORTS_MACCATALYST = NO;")
        lines.append("\t\t\t\tSWIFT_EMIT_LOC_STRINGS = YES;")
        lines.append('\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";')
        lines.append("\t\t\t};")
        lines.append(f"\t\t\tname = {name};")
        lines.append("\t\t};")
    lines.append("/* End XCBuildConfiguration section */")
    lines.append("")

    # XCConfigurationList
    lines.append("/* Begin XCConfigurationList section */")
    lines.append(
        f"\t\t{project_config_list} /* Build configuration list for PBXProject \"LivingRoomEdge\" */ = {{"
    )
    lines.append("\t\t\tisa = XCConfigurationList;")
    lines.append("\t\t\tbuildConfigurations = (")
    lines.append(f"\t\t\t\t{project_config_debug} /* Debug */,")
    lines.append(f"\t\t\t\t{project_config_release} /* Release */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tdefaultConfigurationIsVisible = 0;")
    lines.append("\t\t\tdefaultConfigurationName = Release;")
    lines.append("\t\t};")
    lines.append(
        f"\t\t{target_config_list} /* Build configuration list for PBXNativeTarget \"LivingRoomEdge\" */ = {{"
    )
    lines.append("\t\t\tisa = XCConfigurationList;")
    lines.append("\t\t\tbuildConfigurations = (")
    lines.append(f"\t\t\t\t{sources_build_config_debug} /* Debug */,")
    lines.append(f"\t\t\t\t{sources_build_config_release} /* Release */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tdefaultConfigurationIsVisible = 0;")
    lines.append("\t\t\tdefaultConfigurationName = Release;")
    lines.append("\t\t};")
    lines.append("/* End XCConfigurationList section */")
    lines.append("")

    # XCRemoteSwiftPackageReference
    lines.append("/* Begin XCRemoteSwiftPackageReference section */")
    lines.append(f"\t\t{spm_ref} /* XCRemoteSwiftPackageReference \"google-cast-sdk\" */ = {{")
    lines.append("\t\t\tisa = XCRemoteSwiftPackageReference;")
    lines.append(f'\t\t\trepositoryURL = "{CAST_SPM_URL}";')
    lines.append("\t\t\trequirement = {")
    lines.append("\t\t\t\tkind = upToNextMajorVersion;")
    lines.append(f"\t\t\t\tminimumVersion = {CAST_SPM_VERSION};")
    lines.append("\t\t\t};")
    lines.append("\t\t};")
    lines.append("/* End XCRemoteSwiftPackageReference section */")
    lines.append("")

    # XCSwiftPackageProductDependency
    lines.append("/* Begin XCSwiftPackageProductDependency section */")
    lines.append(f"\t\t{spm_product_dep} /* {CAST_SPM_PRODUCT} */ = {{")
    lines.append("\t\t\tisa = XCSwiftPackageProductDependency;")
    lines.append(f"\t\t\tpackage = {spm_ref} /* XCRemoteSwiftPackageReference \"google-cast-sdk\" */;")
    lines.append(f"\t\t\tproductName = {CAST_SPM_PRODUCT};")
    lines.append("\t\t};")
    lines.append("/* End XCSwiftPackageProductDependency section */")

    lines.append("\t};")
    lines.append(f"\trootObject = {project_id} /* Project object */;")
    lines.append("}")

    PROJ.mkdir(parents=True, exist_ok=True)
    (PROJ / "project.pbxproj").write_text("\n".join(lines) + "\n", encoding="utf-8")
    plugin_n = sum(1 for f in files if f.source_root_path)
    print(
        f"Wrote {PROJ / 'project.pbxproj'} with {len(files)} swift files "
        f"({plugin_n} from plugins/) + SPM {CAST_SPM_PRODUCT}"
    )


if __name__ == "__main__":
    main()
