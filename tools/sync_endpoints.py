#!/usr/bin/env python3
"""Sync config/endpoints.json → platform default string literals.

Edit config/endpoints.json, then run:
  python3 tools/sync_endpoints.py

LAN defaults are mDNS hostnames (brain.local / gateway.local / img-server.local).
Mac co-located Brain stays loopback. Do not write RFC1918 addresses.

Priority at runtime:
  1. Env / .env (Mac) or UserDefaults / SharedPreferences (mobile, after discovery)
  2. Hostname identity written here from config/endpoints.json
  3. Loopback (Mac only)

Does not clear saved mobile settings — change those in-app or reinstall.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.endpoints import (  # noqa: E402
    brain_cloud_base,
    brain_lan_base,
    endpoints_path,
    load_endpoints,
    mac_img_host,
    mac_lan_host,
    mac_service_url,
)

MAC_LOOPBACK_BRAIN = "http://127.0.0.1:9527"


def _sub_file(path: Path, pattern: str, repl: str, *, flags: int = 0, count: int = 0) -> bool:
    if not path.is_file():
        print(f"missing {path.relative_to(ROOT)}")
        return False
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=count, flags=flags)
    if not n:
        print(f"unchanged {path.relative_to(ROOT)} ({pattern[:48]}…)")
        return False
    path.write_text(new, encoding="utf-8")
    print(f"patch {path.relative_to(ROOT)} ×{n}")
    return True


def sync_ios() -> None:
    lan = brain_lan_base()
    cloud = brain_cloud_base()
    video = mac_service_url("video_live_port")

    _sub_file(
        ROOT / "ios/LivingRoomEdge/LivingRoomEdge/Brain/BrainEndpoint.swift",
        r'static let defaultLanBase = "[^"]+"',
        f'static let defaultLanBase = "{lan}"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomEdge/LivingRoomEdge/Brain/BrainEndpoint.swift",
        r'static let defaultCloudBase = "[^"]+"',
        f'static let defaultCloudBase = "{cloud}"',
    )
    _sub_file(
        ROOT / "ios/HomeAgentDev/HomeAgentDev/DevBrainEndpoint.swift",
        r'static let defaultLanBase = "[^"]+"',
        f'static let defaultLanBase = "{lan}"',
    )
    _sub_file(
        ROOT / "ios/HomeAgentDev/HomeAgentDev/DevBrainEndpoint.swift",
        r'static let defaultCloudBase = "[^"]+"',
        f'static let defaultCloudBase = "{cloud}"',
    )
    _sub_file(
        ROOT / "ios/HomeAgentAdmin/HomeAgentAdmin/AdminSettings.swift",
        r'static let defaultBrainURL = "[^"]+"',
        f'static let defaultBrainURL = "{lan}"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomLegacy/LivingRoomLegacy/Services/BrainEndpoint.swift",
        r'static let defaultHomeIntentURL = "[^"]+"',
        f'static let defaultHomeIntentURL = "{lan}/api/v1/intent"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomLegacy/LivingRoomLegacy/Services/BrainEndpoint.swift",
        r'static let cloudIntentURL = "[^"]+"',
        f'static let cloudIntentURL = "{cloud}/api/v1/intent"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomLegacy/LivingRoomLegacy/Services/ParticipantStore.swift",
        r'static let defaultMacIngestURL = "[^"]+"',
        f'static let defaultMacIngestURL = "{video}"',
    )


def sync_android() -> None:
    lan = brain_lan_base()
    cloud = brain_cloud_base()
    _sub_file(
        ROOT
        / "android/living-room-android/src/main/java/com/smarthome/livingroom_android/brain/BrainEndpoint.kt",
        r'const val DEFAULT_LAN_BASE = "[^"]+"',
        f'const val DEFAULT_LAN_BASE = "{lan}"',
    )
    _sub_file(
        ROOT
        / "android/living-room-android/src/main/java/com/smarthome/livingroom_android/brain/BrainEndpoint.kt",
        r'const val DEFAULT_CLOUD_BASE = "[^"]+"',
        f'const val DEFAULT_CLOUD_BASE = "{cloud}"',
    )
    for gradle in (
        ROOT / "android/living-room-android/build.gradle.kts",
        ROOT / "android/app-v2/build.gradle.kts",
    ):
        if not gradle.is_file():
            continue
        text = gradle.read_text(encoding="utf-8")
        text2 = text
        text2 = re.sub(
            r'(buildConfigField\("String",\s*"DEFAULT_BRAIN_BASE_URL",\s*")\\"[^"]+\\"(")',
            rf'\g<1>\\"{lan}\\"\2',
            text2,
        )
        text2 = re.sub(
            r'(buildConfigField\("String",\s*"DEFAULT_CLOUD_BRAIN_BASE_URL",\s*")\\"[^"]+\\"(")',
            rf'\g<1>\\"{cloud}\\"\2',
            text2,
        )
        text2 = re.sub(
            r'http://[^"\\]+:9527/api/v1/devices/living-room/intents',
            f"{lan}/api/v1/devices/living-room/intents",
            text2,
        )
        text2 = re.sub(
            r'http://[^"\\]+:9527/api/v1/intent',
            f"{lan}/api/v1/intent",
            text2,
        )
        if text2 != text:
            gradle.write_text(text2, encoding="utf-8")
            print(f"patch {gradle.relative_to(ROOT)}")
        else:
            print(f"unchanged {gradle.relative_to(ROOT)}")


def sync_mac_scripts() -> None:
    cloud = brain_cloud_base()
    # Same machine as LAN Brain: HTTP is loopback, not brain.local.
    _sub_file(
        ROOT / "mac/deploy/run_mac_edge.home-server.sh",
        r'export MAC_EDGE_BRAIN_URL="[^"]+"',
        f'export MAC_EDGE_BRAIN_URL="{MAC_LOOPBACK_BRAIN}"',
    )
    example = ROOT / "mac/.env.example"
    if example.is_file():
        text = example.read_text(encoding="utf-8")
        lan_j = json.dumps({"lan": MAC_LOOPBACK_BRAIN, "cloud": cloud}, ensure_ascii=False)
        text2 = re.sub(
            r"^MAC_EDGE_BRAIN_URL=.*$",
            f"MAC_EDGE_BRAIN_URL='{lan_j}'",
            text,
            count=1,
            flags=re.M,
        )
        text2 = re.sub(
            r"http://192\.168\.\d+\.\d+:9527",
            MAC_LOOPBACK_BRAIN,
            text2,
        )
        if text2 != text:
            example.write_text(text2, encoding="utf-8")
            print(f"patch {example.relative_to(ROOT)}")


def main() -> int:
    load_endpoints()
    print(f"source {endpoints_path().relative_to(ROOT)}")
    print(f"  brain.lan   = {brain_lan_base()}")
    print(f"  brain.cloud = {brain_cloud_base()}")
    print(f"  mac.host    = {mac_lan_host()}")
    print(f"  img.host    = {mac_img_host()}")
    print(f"  mac loopback Brain = {MAC_LOOPBACK_BRAIN}")
    sync_ios()
    sync_android()
    sync_mac_scripts()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
