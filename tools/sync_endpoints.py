#!/usr/bin/env python3
"""Sync config/endpoints.json → platform default string literals.

Edit config/endpoints.json, then run:
  python3 tools/sync_endpoints.py

Priority at runtime:
  1. Env / .env (Mac) or UserDefaults / SharedPreferences (mobile)
  2. Values written here from config/endpoints.json (fresh-install defaults)
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
    mac_lan_host,
    mac_service_url,
)


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
    mac_host = mac_lan_host()
    video = mac_service_url("video_live_port")
    # LAN device addressing migrates to well-known mDNS hostnames
    # (agent_plans/service_discovery_mdns_migration_v2.md): the mac_edge gateway
    # publishes `_ha-gateway._tcp` under `gateway.local` (hosts video-live ingest).
    gateway_video = re.sub(r"http://[^/]+", "http://gateway.local", video)
    # Brain publishes `_ha-brain._tcp` under `brain.local`; keep the LAN Brain slot
    # on the mDNS hostname instead of a fixed LAN IP.
    brain_lan_dns = re.sub(r"http://[^/]+", "http://brain.local", lan)

    _sub_file(
        ROOT / "ios/LivingRoomEdge/LivingRoomEdge/Brain/BrainEndpoint.swift",
        r'static let defaultLanBase = "[^"]+"',
        f'static let defaultLanBase = "{brain_lan_dns}"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomEdge/LivingRoomEdge/Brain/BrainEndpoint.swift",
        r'static let defaultCloudBase = "[^"]+"',
        f'static let defaultCloudBase = "{cloud}"',
    )
    _sub_file(
        ROOT / "ios/HomeAgentDev/HomeAgentDev/DevBrainEndpoint.swift",
        r'static let defaultLanBase = "[^"]+"',
        f'static let defaultLanBase = "{brain_lan_dns}"',
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
        r'static let homeIntentURL = "[^"]+"',
        f'static let homeIntentURL = "{lan}/api/v1/intent"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomLegacy/LivingRoomLegacy/Services/BrainEndpoint.swift",
        r'static let cloudIntentURL = "[^"]+"',
        f'static let cloudIntentURL = "{cloud}/api/v1/intent"',
    )
    _sub_file(
        ROOT / "ios/LivingRoomLegacy/LivingRoomLegacy/Services/ParticipantStore.swift",
        r'static let defaultMacIngestURL = "[^"]+"',
        f'static let defaultMacIngestURL = "{gateway_video}"',
    )
    _sub_file(
        ROOT / "ios/HomeAgentPickup/HomeAgentPickup/Net/PickupSettings.swift",
        r'return "192\.168\.\d+\.\d+"',
        f'return "{mac_host}"',
        count=1,
    )
    _sub_file(
        ROOT / "ios/HomeAgentPickup/HomeAgentPickup/Net/PickupSettings.swift",
        r'return "http://192\.168\.\d+\.\d+:9527/api/v1/intent"',
        f'return "{lan}/api/v1/intent"',
        count=1,
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
        # Third arg is Kotlin string with escaped quotes: "\"http://...\""
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
            r'http://192\.168\.\d+\.\d+:9527/api/v1/devices/living-room/intents',
            f"{lan}/api/v1/devices/living-room/intents",
            text2,
        )
        text2 = re.sub(
            r'http://192\.168\.\d+\.\d+:9527/api/v1/intent',
            f"{lan}/api/v1/intent",
            text2,
        )
        if text2 != text:
            gradle.write_text(text2, encoding="utf-8")
            print(f"patch {gradle.relative_to(ROOT)}")
        else:
            print(f"unchanged {gradle.relative_to(ROOT)}")


def sync_mac_scripts() -> None:
    lan = brain_lan_base()
    cloud = brain_cloud_base()
    _sub_file(
        ROOT / "mac/deploy/run_mac_edge.home-server.sh",
        r'export MAC_EDGE_BRAIN_URL="[^"]+"',
        f'export MAC_EDGE_BRAIN_URL="{lan}"',
    )
    example = ROOT / "mac/.env.example"
    if example.is_file():
        text = example.read_text(encoding="utf-8")
        lan_j = json.dumps({"lan": lan, "cloud": cloud}, ensure_ascii=False)
        text2 = re.sub(
            r"^MAC_EDGE_BRAIN_URL=.*$",
            f"MAC_EDGE_BRAIN_URL='{lan_j}'",
            text,
            count=1,
            flags=re.M,
        )
        # Keep illustrative comments pointing at the same LAN base.
        text2 = re.sub(r"http://192\.168\.\d+\.\d+:9527", lan, text2)
        if text2 != text:
            example.write_text(text2, encoding="utf-8")
            print(f"patch {example.relative_to(ROOT)}")

    deploy = ROOT / "server/deploy/deploy_lan_brain.sh"
    if deploy.is_file():
        host = lan.split("://", 1)[-1].split(":", 1)[0]
        text = deploy.read_text(encoding="utf-8")
        text2 = re.sub(r"192\.168\.\d+\.\d+", host, text)
        if text2 != text:
            deploy.write_text(text2, encoding="utf-8")
            print(f"patch {deploy.relative_to(ROOT)}")


def main() -> int:
    load_endpoints()
    print(f"source {endpoints_path().relative_to(ROOT)}")
    print(f"  brain.lan   = {brain_lan_base()}")
    print(f"  brain.cloud = {brain_cloud_base()}")
    print(f"  mac.host    = {mac_lan_host()}")
    sync_ios()
    sync_android()
    sync_mac_scripts()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
