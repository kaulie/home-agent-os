#!/usr/bin/env python3
"""One-shot: add HomeAgentDevUITests target to project.pbxproj (run from ios/HomeAgentDev)."""

from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PBX = ROOT / "HomeAgentDev.xcodeproj" / "project.pbxproj"
APP_TARGET = "4E97C4B0EBFF43808A37C7A8"
PROJECT = "A9FC646AC3C44CA2B5D0AC02"
PRODUCTS_GROUP = "BA743925EA084E1681BA3970"
MAIN_GROUP = "F9D44AEE52EF4E89B09F86AB"


def xid() -> str:
    return uuid.uuid4().hex[:24].upper()


def main() -> None:
    text = PBX.read_text(encoding="utf-8")
    if "HomeAgentDevUITests" in text:
        print("UITests target already present")
        return

    test_file_ref = xid()
    test_build_file = xid()
    test_product_ref = xid()
    test_target = xid()
    test_sources = xid()
    test_frameworks = xid()
    test_resources = xid()
    test_group = xid()
    test_dep = xid()
    test_container = xid()
    test_cfg_debug = xid()
    test_cfg_release = xid()
    test_cfg_list = xid()

    insert_build = f"""\t\t{test_build_file} /* MarkdownReaderUITests.swift in Sources */ = {{isa = PBXBuildFile; fileRef = {test_file_ref} /* MarkdownReaderUITests.swift */; }};
"""
    text = text.replace("/* End PBXBuildFile section */", insert_build + "/* End PBXBuildFile section */")

    insert_refs = f"""\t\t{test_product_ref} /* HomeAgentDevUITests.xctest */ = {{isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = HomeAgentDevUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; }};
\t\t{test_file_ref} /* MarkdownReaderUITests.swift */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = MarkdownReaderUITests.swift; sourceTree = "<group>"; }};
"""
    text = text.replace("/* End PBXFileReference section */", insert_refs + "/* End PBXFileReference section */")

    text = text.replace(
        f"\t\t\t\tFFF42CB4C6BB4282B54EA188 /* HomeAgentDev.app */,\n",
        f"\t\t\t\tFFF42CB4C6BB4282B54EA188 /* HomeAgentDev.app */,\n\t\t\t\t{test_product_ref} /* HomeAgentDevUITests.xctest */,\n",
    )
    text = text.replace(
        f"\t\t\tchildren = (\n\t\t\t\tD7589A73BDD648DDBBE59C02 /* HomeAgentDev */,\n",
        f"\t\t\tchildren = (\n\t\t\t\tD7589A73BDD648DDBBE59C02 /* HomeAgentDev */,\n\t\t\t\t{test_group} /* HomeAgentDevUITests */,\n",
    )

    insert_group = f"""\t\t{test_group} /* HomeAgentDevUITests */ = {{
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\t{test_file_ref} /* MarkdownReaderUITests.swift */,
\t\t\t);
\t\t\tpath = HomeAgentDevUITests;
\t\t\tsourceTree = "<group>";
\t\t}};
"""
    text = text.replace("/* End PBXGroup section */", insert_group + "/* End PBXGroup section */")

    insert_target = f"""\t\t{test_target} /* HomeAgentDevUITests */ = {{
\t\t\tisa = PBXNativeTarget;
\t\t\tbuildConfigurationList = {test_cfg_list} /* Build configuration list for PBXNativeTarget "HomeAgentDevUITests" */;
\t\t\tbuildPhases = (
\t\t\t\t{test_sources} /* Sources */,
\t\t\t\t{test_frameworks} /* Frameworks */,
\t\t\t\t{test_resources} /* Resources */,
\t\t\t);
\t\t\tbuildRules = (
\t\t\t);
\t\t\tdependencies = (
\t\t\t\t{test_dep} /* PBXTargetDependency */,
\t\t\t);
\t\t\tname = HomeAgentDevUITests;
\t\t\tproductName = HomeAgentDevUITests;
\t\t\tproductReference = {test_product_ref} /* HomeAgentDevUITests.xctest */;
\t\t\tproductType = "com.apple.product-type.bundle.ui-testing";
\t\t}};
"""
    text = text.replace("/* End PBXNativeTarget section */", insert_target + "/* End PBXNativeTarget section */")

    text = text.replace(
        f"\t\t\ttargets = (\n\t\t\t\t{APP_TARGET} /* HomeAgentDev */,\n",
        f"\t\t\ttargets = (\n\t\t\t\t{APP_TARGET} /* HomeAgentDev */,\n\t\t\t\t{test_target} /* HomeAgentDevUITests */,\n",
    )

    insert_dep = f"""
/* Begin PBXContainerItemProxy section */
\t\t{test_container} /* PBXContainerItemProxy */ = {{
\t\t\tisa = PBXContainerItemProxy;
\t\t\tcontainerPortal = {PROJECT} /* Project object */;
\t\t\tproxyType = 1;
\t\t\tremoteGlobalIDString = {APP_TARGET};
\t\t\tremoteInfo = HomeAgentDev;
\t\t}};
/* End PBXContainerItemProxy section */

/* Begin PBXTargetDependency section */
\t\t{test_dep} /* PBXTargetDependency */ = {{
\t\t\tisa = PBXTargetDependency;
\t\t\ttarget = {APP_TARGET} /* HomeAgentDev */;
\t\t\ttargetProxy = {test_container} /* PBXContainerItemProxy */;
\t\t}};
/* End PBXTargetDependency section */
"""
    text = text.replace("/* Begin PBXResourcesBuildPhase section */", insert_dep + "/* Begin PBXResourcesBuildPhase section */")

    insert_phases = f"""
\t\t{test_frameworks} /* Frameworks */ = {{
\t\t\tisa = PBXFrameworksBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}};
\t\t{test_resources} /* Resources */ = {{
\t\t\tisa = PBXResourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}};
\t\t{test_sources} /* Sources */ = {{
\t\t\tisa = PBXSourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t\t{test_build_file} /* MarkdownReaderUITests.swift in Sources */,
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t}};
"""
    text = text.replace("/* End PBXSourcesBuildPhase section */", insert_phases + "/* End PBXSourcesBuildPhase section */")

    test_settings = """
\t\t\t\tCODE_SIGN_STYLE = Automatic;
\t\t\t\tCURRENT_PROJECT_VERSION = 1;
\t\t\t\tDEVELOPMENT_TEAM = "";
\t\t\t\tGENERATE_INFOPLIST_FILE = YES;
\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = 16.0;
\t\t\t\tMARKETING_VERSION = 0.1.0;
\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = com.gaolei.homeagent.dev.uitests;
\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";
\t\t\t\tSWIFT_EMIT_LOC_STRINGS = NO;
\t\t\t\tSWIFT_VERSION = 5.0;
\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\t\tTEST_TARGET_NAME = HomeAgentDev;
"""

    insert_cfg = f"""\t\t{test_cfg_debug} /* Debug */ = {{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{{test_settings}
\t\t\t}};
\t\t\tname = Debug;
\t\t}};
\t\t{test_cfg_release} /* Release */ = {{
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {{{test_settings}
\t\t\t}};
\t\t\tname = Release;
\t\t}};
"""
    text = text.replace("/* End XCBuildConfiguration section */", insert_cfg + "/* End XCBuildConfiguration section */")

    insert_cfg_list = f"""\t\t{test_cfg_list} /* Build configuration list for PBXNativeTarget "HomeAgentDevUITests" */ = {{
\t\t\tisa = XCConfigurationList;
\t\t\tbuildConfigurations = (
\t\t\t\t{test_cfg_debug} /* Debug */,
\t\t\t\t{test_cfg_release} /* Release */,
\t\t\t);
\t\t\tdefaultConfigurationIsVisible = 0;
\t\t\tdefaultConfigurationName = Release;
\t\t}};
"""
    text = text.replace("/* End XCConfigurationList section */", insert_cfg_list + "/* End XCConfigurationList section */")

    PBX.write_text(text, encoding="utf-8")
    print(f"Patched {PBX} with HomeAgentDevUITests target")


if __name__ == "__main__":
    main()
