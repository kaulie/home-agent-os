#!/usr/bin/env python3
"""GoPro gpControl reference driver (Python).

Aligned with plugins/gopro-camera iOS GoProDriver paths.
Default camera host: http://10.5.5.9

Usage:
  python3 driver.py status
  python3 driver.py capture
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "http://10.5.5.9"

PATH_MODE_PHOTO = "/gp/gpControl/command/mode?p=1"
PATH_SUB_MODE_PHOTO_SINGLE = "/gp/gpControl/command/sub_mode?mode=1&sub_mode=0"
PATH_STATUS = "/gp/gpControl/status"
PATH_SHUTTER_START = "/gp/gpControl/command/shutter?p=1"
PATH_SHUTTER_STOP = "/gp/gpControl/command/shutter?p=0"
PATH_MEDIA_LIST = "/gp/gpMediaList"


class GoProDriver:
    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 8.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> tuple[int, bytes]:
        url = self.host + path
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.getcode(), resp.read()

    def status(self) -> dict:
        code, body = self._get(PATH_STATUS)
        text = body.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        return {"http_status": code, "body": payload}

    def capture_photo(self) -> dict:
        steps: list[dict] = []
        for path in (PATH_MODE_PHOTO, PATH_SUB_MODE_PHOTO_SINGLE, PATH_SHUTTER_START):
            code, body = self._get(path)
            steps.append(
                {
                    "path": path,
                    "http_status": code,
                    "body": body.decode("utf-8", errors="replace")[:200],
                }
            )
        return {"steps": steps}

    def stop_shutter(self) -> dict:
        code, body = self._get(PATH_SHUTTER_STOP)
        return {
            "http_status": code,
            "body": body.decode("utf-8", errors="replace")[:200],
        }

    def media_list(self) -> dict:
        code, body = self._get(PATH_MEDIA_LIST)
        text = body.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        return {"http_status": code, "body": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GoPro gpControl reference driver")
    parser.add_argument(
        "command",
        choices=["status", "capture", "stop", "media"],
        help="command to run",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="camera base URL")
    args = parser.parse_args(argv)

    driver = GoProDriver(host=args.host)
    try:
        if args.command == "status":
            result = driver.status()
        elif args.command == "capture":
            result = driver.capture_photo()
        elif args.command == "stop":
            result = driver.stop_shutter()
        else:
            result = driver.media_list()
    except urllib.error.URLError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("hint: join GoPro Wi-Fi first (default host http://10.5.5.9)", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
