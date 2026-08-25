"""Mac Edge: video.live_stream is produced on iPhone; Mac only ingests.

If Brain mistakenly schedules this capability as a plan step on Mac, refuse.
"""

from __future__ import annotations

from typing import Any


class VideoLiveStreamError(Exception):
    pass


def run_from_params(_params: dict[str, Any]) -> tuple[str, dict[str, str]]:
    raise VideoLiveStreamError(
        "video.live_stream 是 iPhone 实时视频输入（kind=input），"
        "由互动「直播」页或 Larix 自管理推流；不由计划逐步执行"
    )
