#!/usr/bin/env python3
"""Generate a minimal Xcode project for HomeAgentRelay."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "HomeAgentRelay"
PROJ = ROOT / "HomeAgentRelay.xcodeproj"
APP_NAME = "HomeAgentRelay"
BUNDLE_ID = "com.gaolei.homeagent.relay"


def xid() -> str:
    return uuid.uuid4().hex[:24].upper()


@dataclass(frozen=True)
class SwiftFile:
    path: Path
    group_path: str
    name: str


def collect_swift() -> list[SwiftFile]:
    files: list[SwiftFile] = []
    for f in sorted(SRC.rglob("*.swift")):
        rel = f.relative_to(SRC)
        parent = "" if str(rel.parent) == "." else str(rel.parent)
        files.append(SwiftFile(path=f, group_path=parent, name=f.name))
    return files


def write_scheme(target_id: str) -> None:
    scheme_dir = PROJ / "xcshareddata" / "xcschemes"
    scheme_dir.mkdir(parents=True, exist_ok=True)
    scheme_path = scheme_dir / f"{APP_NAME}.xcscheme"
    scheme_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme
   LastUpgradeVersion = "1500"
   version = "1.7">
   <BuildAction
      parallelizeBuildables = "YES"
      buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry
            buildForTesting = "YES"
            buildForRunning = "YES"
            buildForProfiling = "YES"
            buildForArchiving = "YES"
            buildForAnalyzing = "YES">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{target_id}"
               BuildableName = "{APP_NAME}.app"
               BlueprintName = "{APP_NAME}"
               ReferencedContainer = "container:{APP_NAME}.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      shouldUseLaunchSchemeArgsEnv = "YES"
      shouldAutocreateTestPlan = "YES">
   </TestAction>
   <LaunchAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      launchStyle = "0"
      useCustomWorkingDirectory = "NO"
      ignoresPersistentStateOnLaunch = "NO"
      debugDocumentVersioning = "YES"
      debugServiceExtension = "internal"
      allowLocationSimulation = "YES">
      <BuildableProductRunnable
         runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{target_id}"
            BuildableName = "{APP_NAME}.app"
            BlueprintName = "{APP_NAME}"
            ReferencedContainer = "container:{APP_NAME}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction
      buildConfiguration = "Release"
      shouldUseLaunchSchemeArgsEnv = "YES"
      savedToolIdentifier = ""
      useCustomWorkingDirectory = "NO"
      debugDocumentVersioning = "YES">
      <BuildableProductRunnable
         runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{target_id}"
            BuildableName = "{APP_NAME}.app"
            BlueprintName = "{APP_NAME}"
            ReferencedContainer = "container:{APP_NAME}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction
      buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction
      buildConfiguration = "Release"
      revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
""",
        encoding="utf-8",
    )


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

    file_refs: dict[SwiftFile, str] = {}
    build_files: dict[SwiftFile, str] = {}
    for f in files:
        file_refs[f] = xid()
        build_files[f] = xid()
    info_ref = xid()

    group_ids: dict[str, str] = {"": src_group}
    all_group_paths: set[str] = set(group_ids.keys())
    for f in files:
        if f.group_path:
            parts = list(Path(f.group_path).parts)
            path = ""
            for part in parts:
                path = f"{path}/{part}" if path else part
                all_group_paths.add(path)
    for path in sorted(all_group_paths):
        if path and path not in group_ids:
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

    lines.append("/* Begin PBXBuildFile section */")
    for f, bid in build_files.items():
        lines.append(
            f"\t\t{bid} /* {f.name} in Sources */ = {{isa = PBXBuildFile; fileRef = {file_refs[f]} /* {f.name} */; }};"
        )
    lines.append("/* End PBXBuildFile section */")
    lines.append("")

    lines.append("/* Begin PBXFileReference section */")
    lines.append(
        f"\t\t{product_ref} /* {APP_NAME}.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = {APP_NAME}.app; sourceTree = BUILT_PRODUCTS_DIR; }};"
    )
    for f, fid in file_refs.items():
        lines.append(
            f"\t\t{fid} /* {f.name} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {f.name}; sourceTree = \"<group>\"; }};"
        )
    lines.append(
        f"\t\t{info_ref} /* Info.plist */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = \"<group>\"; }};"
    )
    lines.append("/* End PBXFileReference section */")
    lines.append("")

    lines.append("/* Begin PBXFrameworksBuildPhase section */")
    lines.append(f"\t\t{frameworks_phase} /* Frameworks */ = {{")
    lines.append("\t\t\tisa = PBXFrameworksBuildPhase;")
    lines.append("\t\t\tbuildActionMask = 2147483647;")
    lines.append("\t\t\tfiles = (")
    lines.append("\t\t\t);")
    lines.append("\t\t\trunOnlyForDeploymentPostprocessing = 0;")
    lines.append("\t\t};")
    lines.append("/* End PBXFrameworksBuildPhase section */")
    lines.append("")

    lines.append("/* Begin PBXGroup section */")
    lines.append(f"\t\t{main_group} = {{")
    lines.append("\t\t\tisa = PBXGroup;")
    lines.append("\t\t\tchildren = (")
    lines.append(f"\t\t\t\t{src_group} /* {APP_NAME} */,")
    lines.append(f"\t\t\t\t{products_group} /* Products */,")
    lines.append("\t\t\t);")
    lines.append('\t\t\tsourceTree = "<group>";')
    lines.append("\t\t};")
    lines.append(f"\t\t{products_group} /* Products */ = {{")
    lines.append("\t\t\tisa = PBXGroup;")
    lines.append("\t\t\tchildren = (")
    lines.append(f"\t\t\t\t{product_ref} /* {APP_NAME}.app */,")
    lines.append("\t\t\t);")
    lines.append("\t\t\tname = Products;")
    lines.append('\t\t\tsourceTree = "<group>";')
    lines.append("\t\t};")

    for gpath, gid in group_ids.items():
        name = gpath.split("/")[-1] if gpath else APP_NAME
        lines.append(f"\t\t{gid} /* {name} */ = {{")
        lines.append("\t\t\tisa = PBXGroup;")
        lines.append("\t\t\tchildren = (")
        for cid in group_children(gpath):
            lines.append(f"\t\t\t\t{cid},")
        lines.append("\t\t\t);")
        if gpath == "":
            lines.append(f"\t\t\tpath = {APP_NAME};")
        else:
            lines.append(f"\t\t\tpath = {name};")
        lines.append('\t\t\tsourceTree = "<group>";')
        lines.append("\t\t};")
    lines.append("/* End PBXGroup section */")
    lines.append("")

    lines.append("/* Begin PBXNativeTarget section */")
    lines.append(f"\t\t{target_id} /* {APP_NAME} */ = {{")
    lines.append("\t\t\tisa = PBXNativeTarget;")
    lines.append(
        f"\t\t\tbuildConfigurationList = {target_config_list} /* Build configuration list for PBXNativeTarget \"{APP_NAME}\" */;"
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
    lines.append(f"\t\t\tname = {APP_NAME};")
    lines.append("\t\t\tpackageProductDependencies = (")
    lines.append("\t\t\t);")
    lines.append(f"\t\t\tproductName = {APP_NAME};")
    lines.append(f"\t\t\tproductReference = {product_ref} /* {APP_NAME}.app */;")
    lines.append('\t\t\tproductType = "com.apple.product-type.application";')
    lines.append("\t\t};")
    lines.append("/* End PBXNativeTarget section */")
    lines.append("")

    lines.append("/* Begin PBXProject section */")
    lines.append(f"\t\t{project_id} /* Project object */ = {{")
    lines.append("\t\t\tisa = PBXProject;")
    lines.append("\t\t\tattributes = {")
    lines.append("\t\t\t\tBuildIndependentTargetsInParallel = 1;")
    lines.append("\t\t\t\tLastSwiftUpdateCheck = 1500;")
    lines.append("\t\t\t\tLastUpgradeCheck = 1500;")
    lines.append("\t\t\t};")
    lines.append(
        f"\t\t\tbuildConfigurationList = {project_config_list} /* Build configuration list for PBXProject \"{APP_NAME}\" */;"
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
    lines.append("\t\t\t);")
    lines.append(f"\t\t\tproductRefGroup = {products_group} /* Products */;")
    lines.append('\t\t\tprojectDirPath = "";')
    lines.append('\t\t\tprojectRoot = "";')
    lines.append("\t\t\ttargets = (")
    lines.append(f"\t\t\t\t{target_id} /* {APP_NAME} */,")
    lines.append("\t\t\t);")
    lines.append("\t\t};")
    lines.append("/* End PBXProject section */")
    lines.append("")

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
        lines.append("\t\t\t\tCODE_SIGN_STYLE = Automatic;")
        lines.append("\t\t\t\tCURRENT_PROJECT_VERSION = 1;")
        lines.append('\t\t\t\tDEVELOPMENT_TEAM = "";')
        lines.append("\t\t\t\tENABLE_PREVIEWS = YES;")
        lines.append("\t\t\t\tGENERATE_INFOPLIST_FILE = NO;")
        lines.append(f"\t\t\t\tINFOPLIST_FILE = {APP_NAME}/Info.plist;")
        lines.append("\t\t\t\tLD_RUNPATH_SEARCH_PATHS = (")
        lines.append('\t\t\t\t\t"$(inherited)",')
        lines.append('\t\t\t\t\t"@executable_path/Frameworks",')
        lines.append("\t\t\t\t);")
        lines.append("\t\t\t\tMARKETING_VERSION = 0.1.0;")
        lines.append(f"\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID};")
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

    lines.append("/* Begin XCConfigurationList section */")
    lines.append(
        f"\t\t{project_config_list} /* Build configuration list for PBXProject \"{APP_NAME}\" */ = {{"
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
        f"\t\t{target_config_list} /* Build configuration list for PBXNativeTarget \"{APP_NAME}\" */ = {{"
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

    lines.append("\t};")
    lines.append(f"\trootObject = {project_id} /* Project object */;")
    lines.append("}")

    PROJ.mkdir(parents=True, exist_ok=True)
    (PROJ / "project.pbxproj").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_scheme(target_id)
    print(f"Wrote {PROJ / 'project.pbxproj'} with {len(files)} swift files")


if __name__ == "__main__":
    main()
