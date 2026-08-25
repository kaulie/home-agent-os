"""Per-trial wall-clock log. One ISO timestamp per action the report needs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


def iso_now(now: Callable[[], datetime] | None = None) -> str:
    dt = now() if now is not None else datetime.now().astimezone()
    return dt.isoformat(timespec="milliseconds")


class TrialTimeline:
    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now
        self.events: list[dict[str, Any]] = []

    def mark(self, event: str, label: str, *, extra: str = "") -> str:
        at = iso_now(self._now)
        item: dict[str, Any] = {"at": at, "event": event, "label": label}
        if extra:
            item["extra"] = extra
        self.events.append(item)
        return at

    def absorb_loopback(
        self,
        sidecar: dict[str, Any] | None,
        *,
        which: str,
    ) -> None:
        """Copy play/loopback stamps written during afplay (more precise than utter wrap)."""
        if not isinstance(sidecar, dict):
            return
        phrase = "唤醒词" if which == "wake" else "命令"
        started = str(sidecar.get("play_started_at") or "")
        ended = str(sidecar.get("play_ended_at") or "")
        confirmed = str(sidecar.get("confirmed_at") or ended)
        heard = sidecar.get("heard")
        ratio = sidecar.get("ratio")
        extra = f"heard={heard} ratio={ratio}"
        if started:
            self.events.append(
                {
                    "at": started,
                    "event": f"{which}_play_trigger",
                    "label": f"{phrase}开始播放",
                    "extra": extra,
                }
            )
        if ended:
            self.events.append(
                {
                    "at": ended,
                    "event": f"{which}_play_done",
                    "label": f"{phrase}播放结束",
                }
            )
        if confirmed:
            self.events.append(
                {
                    "at": confirmed,
                    "event": f"{which}_pickup_confirm",
                    "label": f"拾音确认（{phrase}）",
                    "extra": extra,
                }
            )

    def absorb_wake_reply(self, blob: dict[str, Any] | None) -> None:
        if not isinstance(blob, dict):
            return
        started = str(blob.get("listen_started_at") or "")
        ended = str(blob.get("listen_ended_at") or "")
        stt_at = str(blob.get("stt_ended_at") or "")
        heard = blob.get("heard")
        text = str(blob.get("text") or "")
        extra = f"heard={heard} text={text!r}"
        if started:
            self.events.append(
                {
                    "at": started,
                    "event": "wake_reply_listen_start",
                    "label": "听台灯应答「在呢」开始",
                }
            )
        if ended:
            self.events.append(
                {
                    "at": ended,
                    "event": "wake_reply_listen_done",
                    "label": "听台灯应答结束",
                    "extra": extra,
                }
            )
        if stt_at:
            self.events.append(
                {
                    "at": stt_at,
                    "event": "wake_reply_stt_done",
                    "label": "拾音转写完成",
                    "extra": extra,
                }
            )

    def to_dict(self) -> dict[str, Any]:
        ordered = sorted(self.events, key=lambda e: str(e.get("at") or ""))
        lines = []
        for item in ordered:
            extra = str(item.get("extra") or "")
            tail = f"  {extra}" if extra else ""
            lines.append(f"{item['at']}  {item['label']}{tail}")
        return {
            "events": ordered,
            "text": "\n".join(lines),
        }
