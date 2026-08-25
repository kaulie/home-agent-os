"""Phase 1: one closed-loop trial.

Play is not SUCCESS. SUCCESS is lamp-on from an independent verifier.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mac_edge.plugins.voice_test.brain_capture import BrainCaptureError
from mac_edge.plugins.voice_test.profile import VoiceProfile, VoiceProfileError, build_profile, pause_window_risk
from mac_edge.plugins.voice_test.store import append_trial, trial_dir
from mac_edge.plugins.voice_test.timeline import TrialTimeline
from mac_edge.plugins.voice_test.tts import VoiceTtsError, utter_text
from mac_edge.plugins.voice_test.verify import LampVerifier, VerifyResult, VisionAskVerifier
from mac_edge.plugins.voice_test.webcam import WebcamError, capture_still

log = logging.getLogger("mac_edge.voice_test.trial")


class VoiceTestError(Exception):
    pass


@dataclass
class TrialHooks:
    utter: Callable[..., Path]
    capture: Callable[..., Path]
    sleep: Callable[[float], None]
    verifier: LampVerifier
    upload: Callable[..., Any] | None = None
    now: Callable[[], datetime] | None = None
    persist: Callable[[dict[str, Any]], Path] | None = None
    listen_wake_reply: Callable[..., dict[str, Any]] | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_asset_sidecar(image_path: str | Path) -> dict[str, Any] | None:
    return _read_json_file(Path(image_path).with_suffix(".asset.json"))


def _asset_id_of(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("asset_id") or "").strip()
    return str(ref or "").strip()


def playback_spec(profile: VoiceProfile, *, clip_path: str) -> dict[str, str]:
    clip = (clip_path or "").strip()
    if clip:
        return {
            "kind": "clip",
            "label": "录音",
            "backend": "",
            "voice": "",
            "clip_path": clip,
        }
    return {
        "kind": "tts",
        "label": "标准人声 TTS",
        "backend": profile.backend,
        "voice": profile.voice,
        "clip_path": "",
    }


def _read_loopback_sidecar(audio_path: str) -> dict[str, Any] | None:
    if not audio_path:
        return None
    return _read_json_file(Path(audio_path + ".loopback.json"))


def _as_text_map(outputs: dict[str, Any]) -> dict[str, str]:
    wire: dict[str, str] = {}
    for key, value in outputs.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            wire[key] = json.dumps(value, ensure_ascii=False)
        else:
            wire[key] = str(value)
    return wire


def _upload_photo(path: Path, *, preferred_dest: str = "lan") -> dict[str, str]:
    from mac_edge.asset.img_upload import ImgUploadError, upload_image_file

    try:
        uploaded = upload_image_file(path, preferred_dest=preferred_dest)
    except ImgUploadError as e:
        raise VoiceTestError(f"验证图上传失败（{e}）。") from e
    return {
        "photo_url": uploaded.photo_url,
        "saved_as": uploaded.saved_as,
        "dest": uploaded.dest,
    }


def _register_asset(asset: Any, uploaded: dict[str, str], *, producer: str) -> dict[str, Any] | None:
    if asset is None:
        return None
    try:
        ref = asset.register_from_upload_url(
            photo_url=str(uploaded.get("photo_url") or ""),
            saved_as=str(uploaded.get("saved_as") or "") or None,
            producer=producer,
            mime_type="image/jpeg",
        )
    except Exception as e:
        log.warning("asset register skipped: %s", e)
        return None
    return ref.to_dict() if hasattr(ref, "to_dict") else {"asset_id": str(ref)}


def _verify_image(
    path: Path,
    *,
    deps: TrialHooks,
    profile: VoiceProfile,
    asset: Any,
    producer: str,
) -> tuple[VerifyResult, dict[str, Any] | None, str]:
    meta = _read_asset_sidecar(path) or {}
    ref = meta.get("asset_ref") if isinstance(meta.get("asset_ref"), dict) else None
    url = str(meta.get("content_url") or "")
    if not url:
        if deps.upload is None:
            return (
                VerifyResult("unknown", "", "none", "upload_skipped"),
                ref,
                "",
            )
        uploaded = deps.upload(path)
        url = str(uploaded.get("photo_url") or "")
        if ref is None:
            ref = _register_asset(asset, uploaded, producer=producer)
    result = deps.verifier.verify(photo_url=url, query=profile.verify_query)
    return result, ref, url


def _pickup_report(
    wake_audio: str,
    command_audio: str,
    wake_reply: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    from mac_edge.plugins.voice_test.wake_reply import transcribe_pickup_channels

    wake_lb = _read_loopback_sidecar(wake_audio) or {}
    cmd_lb = _read_loopback_sidecar(command_audio) or {}
    rows = transcribe_pickup_channels(
        [
            (
                "wake_play",
                str(wake_lb.get("wav_path") or ""),
                "第一句播放回录",
            ),
            (
                "command_play",
                str(cmd_lb.get("wav_path") or ""),
                "第二句播放回录",
            ),
        ]
    )
    rows.insert(
        1,
        {
            "channel": "pause_window",
            "role": "唤醒后暂停窗（听在呢）",
            "wav": str(wake_reply.get("wav") or ""),
            "text": str(wake_reply.get("text") or ""),
            "error": str(wake_reply.get("error") or ""),
        },
    )
    lines = [
        f"{row['channel']}: {(row.get('text') or '').strip() or '（空）'}"
        for row in rows
    ]
    return rows, "\n".join(lines)


def _judge(
    *,
    before: VerifyResult | None,
    after: VerifyResult,
) -> tuple[str, str]:
    """Return (result, error_reason). Playback is ignored."""
    if before is not None and before.is_on:
        return "INVALID", "lamp_already_on"
    if after.state == "unknown":
        return "FAIL", after.error_reason or "verify_unknown"
    if after.is_on:
        return "SUCCESS", ""
    return "FAIL", "lamp_not_on"


def run_trial(
    *,
    profile: VoiceProfile,
    experiment_id: str = "",
    trial_id: str = "",
    skip_play: bool = False,
    skip_verify: bool = False,
    asset: Any = None,
    hooks: TrialHooks | None = None,
) -> dict[str, Any]:
    """Run one generate → play → wait → capture → verify → record cycle."""
    t0 = time.perf_counter()
    eid = (experiment_id or "").strip() or _new_id()
    tid = (trial_id or "").strip() or _new_id()
    work = trial_dir(eid, tid)
    live_audio = hooks is None
    if hooks is None:
        capture_fn = capture_still
        if profile.capture_backend == "gopro":
            from mac_edge.plugins.voice_test.brain_capture import capture_still as gopro_capture

            capture_fn = gopro_capture
        from mac_edge.plugins.voice_test.wake_reply import record_wake_reply_window

        deps = TrialHooks(
            utter=utter_text,
            capture=capture_fn,
            sleep=time.sleep,
            verifier=VisionAskVerifier(),
            upload=_upload_photo,
            persist=append_trial,
            listen_wake_reply=record_wake_reply_window,
        )
    else:
        deps = hooks
    clock = TrialTimeline(now=deps.now)
    clock.mark("trial_start", "试验开始")
    stamp = clock.events[0]["at"]

    before_path = ""
    after_path = ""
    wake_audio = ""
    command_audio = ""
    before_verify: VerifyResult | None = None
    after_verify: VerifyResult | None = None
    before_asset: dict[str, Any] | None = None
    after_asset: dict[str, Any] | None = None
    after_url = ""
    error_reason = ""
    result = "FAIL"
    wake_reply: dict[str, Any] = {
        "heard": None,
        "text": "",
        "wav": "",
        "source": "skipped",
        "error": "",
    }

    def _persist(local_result: str, local_reason: str) -> dict[str, Any]:
        total_ms = int((time.perf_counter() - t0) * 1000)
        clock.mark(
            "judged",
            f"最终结果 {local_result}",
            extra=(local_reason or "ok")
            + f" speed={profile.speed} volume={profile.volume}"
            + f" pause_ms={profile.wake_word_pause_ms}",
        )
        timeline = clock.to_dict()
        pickup_rows, pickup_text = _pickup_report(
            wake_audio, command_audio, wake_reply
        )
        wake_play = playback_spec(profile, clip_path=profile.wake_audio)
        command_play = playback_spec(profile, clip_path=profile.command_audio)
        record: dict[str, Any] = {
            "experiment_id": eid,
            "trial_id": tid,
            "timestamp": stamp,
            "voice_profile": profile.to_dict(),
            "command": profile.command,
            "wake_word": profile.wake_word,
            "audio_file": command_audio,
            "wake_audio_file": wake_audio,
            "wake_loopback": _read_loopback_sidecar(wake_audio),
            "command_loopback": _read_loopback_sidecar(command_audio),
            "result": local_result,
            "verification_result": (
                (before_verify.state if local_result == "INVALID" and before_verify else "")
                or (after_verify.state if after_verify else "")
            ),
            "verification_answer": (
                (before_verify.answer_text if local_result == "INVALID" and before_verify and not after_verify else "")
                or (after_verify.answer_text if after_verify else "")
            ),
            "verification_source": (
                (before_verify.source if local_result == "INVALID" and before_verify and not after_verify else "")
                or (after_verify.source if after_verify else "")
            ),
            "verification_image": after_path or before_path,
            "before_image": before_path,
            "before_state": before_verify.state if before_verify else "",
            "before_asset_ref": before_asset,
            "before_asset_id": _asset_id_of(before_asset),
            "after_asset_ref": after_asset,
            "after_asset_id": _asset_id_of(after_asset),
            "asset_ref": after_asset,
            "playback": {
                "wake": wake_play,
                "command": command_play,
            },
            "playback_kind": command_play["kind"],
            "playback_label": (
                f"唤醒={wake_play['label']}"
                + (f"（{wake_play['backend']}/{wake_play['voice']}）" if wake_play["kind"] == "tts" else "")
                + f"；命令={command_play['label']}"
                + (
                    f"（{command_play['backend']}/{command_play['voice']}）"
                    if command_play["kind"] == "tts"
                    else ""
                )
                + f"；speed={profile.speed} volume={profile.volume}"
                + f" voice={profile.voice} pitch={profile.pitch or 'default'}"
                + f" settle_ms={profile.settle_ms}"
            ),
            "pickup_transcripts": pickup_rows,
            "pickup_text": pickup_text,
            "latency_ms": total_ms,
            "error_reason": local_reason,
            "settle_ms": profile.settle_ms,
            "wake_word_pause_ms": profile.wake_word_pause_ms,
            "pause_risk": pause_window_risk(profile.wake_word_pause_ms),
            "speed": profile.speed,
            "volume": profile.volume,
            "voice": profile.voice,
            "backend": profile.backend,
            "pitch": profile.pitch,
            "knobs": {
                "backend": profile.backend,
                "voice": profile.voice,
                "speed": profile.speed,
                "volume": profile.volume,
                "pitch": profile.pitch,
                "wake_word_pause_ms": profile.wake_word_pause_ms,
                "settle_ms": profile.settle_ms,
                "say_rate_wpm": profile.say_rate_wpm() if profile.backend == "say" else "",
                "playback_wake": wake_play["label"],
                "playback_command": command_play["label"],
            },
            "wake_reply_heard": wake_reply.get("heard"),
            "wake_reply": wake_reply,
            "timeline": timeline,
            "timeline_text": timeline["text"],
        }
        persist = deps.persist or append_trial
        record["store_path"] = str(persist(record))
        log.info(
            "voice_test trial=%s result=%s reason=%s latency_ms=%s",
            tid,
            local_result,
            local_reason or "-",
            total_ms,
        )
        return record

    try:
        if profile.capture_before and not skip_verify and not skip_play:
            before_file = work / "before.jpg"
            clock.mark("before_capture_trigger", "拍 before 触发")
            deps.capture(before_file, device=profile.webcam_device)
            clock.mark("before_capture_done", "拍 before 完成")
            before_path = str(before_file)
            clock.mark("before_verify_start", "看 before 图开始")
            before_verify, before_asset, _before_url = _verify_image(
                Path(before_path),
                deps=deps,
                profile=profile,
                asset=asset,
                producer="voice_test.run_trial.before",
            )
            clock.mark(
                "before_verify_done",
                "看 before 图完成",
                extra=before_verify.answer_text,
            )
            if before_verify is not None and before_verify.is_on:
                result, error_reason = "INVALID", "lamp_already_on"
                return _persist(result, error_reason)

        if not skip_play:
            if live_audio:
                from mac_edge.plugins.voice_test.tts import play_audio, prepare_utterance
                from mac_edge.plugins.voice_test.wake_reply import finish_wake_reply_stt

                clock.mark(
                    "wake_prepare",
                    "第一句开始合成",
                    extra=f"{profile.wake_word} · {playback_spec(profile, clip_path=profile.wake_audio)['label']}",
                )
                wake_path = prepare_utterance(
                    profile.wake_word,
                    work / "wake",
                    profile=profile,
                    clip_path=profile.wake_audio,
                )
                clock.mark(
                    "command_prepare",
                    "第二句开始合成",
                    extra=f"{profile.command} · {playback_spec(profile, clip_path=profile.command_audio)['label']}",
                )
                cmd_path = prepare_utterance(
                    profile.command,
                    work / "command",
                    profile=profile,
                    clip_path=profile.command_audio,
                )
                play_audio(
                    wake_path,
                    volume=profile.volume,
                    confirm=profile.confirm_playback,
                    heard_wav=wake_path.with_name(wake_path.stem + ".heard.wav"),
                )
                wake_audio = str(wake_path)
                wake_lb = _read_loopback_sidecar(wake_audio)
                if wake_lb and wake_lb.get("play_started_at"):
                    clock.absorb_loopback(wake_lb, which="wake")
                else:
                    clock.mark(
                        "wake_play_trigger",
                        "第一句触发",
                        extra=f"{profile.wake_word} · {playback_spec(profile, clip_path=profile.wake_audio)['label']}",
                    )
                    clock.mark(
                        "wake_pickup_confirm",
                        "拾音确认（唤醒词）",
                        extra="sidecar_missing",
                    )
                if profile.wake_word_pause_ms:
                    if deps.listen_wake_reply is not None:
                        wake_reply = deps.listen_wake_reply(
                            work / "wake_reply.wav", profile.wake_word_pause_ms
                        )
                    else:
                        deps.sleep(profile.wake_word_pause_ms / 1000.0)
                play_audio(
                    cmd_path,
                    volume=profile.volume,
                    confirm=profile.confirm_playback,
                    heard_wav=cmd_path.with_name(cmd_path.stem + ".heard.wav"),
                    skip_ambient=True,
                )
                command_audio = str(cmd_path)
                cmd_lb = _read_loopback_sidecar(command_audio)
                if cmd_lb and cmd_lb.get("play_started_at"):
                    clock.absorb_loopback(cmd_lb, which="command")
                else:
                    clock.mark(
                        "command_play_trigger",
                        "第二句触发",
                        extra=f"{profile.command} · {playback_spec(profile, clip_path=profile.command_audio)['label']}",
                    )
                    clock.mark(
                        "command_pickup_confirm",
                        "拾音确认（命令）",
                        extra="sidecar_missing",
                    )
                if str(wake_reply.get("source") or "") == "recorded":
                    wake_reply = finish_wake_reply_stt(wake_reply)
                clock.absorb_wake_reply(wake_reply)
            else:
                clock.mark(
                    "wake_prepare",
                    "第一句开始合成",
                    extra=f"{profile.wake_word} · {playback_spec(profile, clip_path=profile.wake_audio)['label']}",
                )
                wake_path = deps.utter(
                    profile.wake_word,
                    work / "wake",
                    profile=profile,
                    clip_path=profile.wake_audio,
                )
                wake_audio = str(wake_path)
                wake_lb = _read_loopback_sidecar(wake_audio)
                if wake_lb and wake_lb.get("play_started_at"):
                    clock.absorb_loopback(wake_lb, which="wake")
                else:
                    clock.mark(
                        "wake_play_trigger",
                        "第一句触发",
                        extra=f"{profile.wake_word} · {playback_spec(profile, clip_path=profile.wake_audio)['label']}",
                    )
                    clock.mark(
                        "wake_pickup_confirm",
                        "拾音确认（唤醒词）",
                        extra="sidecar_missing",
                    )
                if profile.wake_word_pause_ms:
                    if deps.listen_wake_reply is not None:
                        wake_reply = deps.listen_wake_reply(
                            work / "wake_reply.wav", profile.wake_word_pause_ms
                        )
                    else:
                        deps.sleep(profile.wake_word_pause_ms / 1000.0)
                clock.mark(
                    "command_prepare",
                    "第二句开始合成",
                    extra=f"{profile.command} · {playback_spec(profile, clip_path=profile.command_audio)['label']}",
                )
                cmd_path = deps.utter(
                    profile.command,
                    work / "command",
                    profile=profile,
                    clip_path=profile.command_audio,
                )
                command_audio = str(cmd_path)
                cmd_lb = _read_loopback_sidecar(command_audio)
                if cmd_lb and cmd_lb.get("play_started_at"):
                    clock.absorb_loopback(cmd_lb, which="command")
                else:
                    clock.mark(
                        "command_play_trigger",
                        "第二句触发",
                        extra=f"{profile.command} · {playback_spec(profile, clip_path=profile.command_audio)['label']}",
                    )
                    clock.mark(
                        "command_pickup_confirm",
                        "拾音确认（命令）",
                        extra="sidecar_missing",
                    )
                clock.absorb_wake_reply(wake_reply)

        if profile.settle_ms:
            clock.mark("settle_start", "等灯响应开始", extra=f"{profile.settle_ms}ms")
            deps.sleep(profile.settle_ms / 1000.0)
            clock.mark("settle_done", "等灯响应结束")

        if not skip_verify:
            after_file = work / "after.jpg"
            clock.mark("after_capture_trigger", "拍 after 触发")
            deps.capture(after_file, device=profile.webcam_device)
            clock.mark("after_capture_done", "拍 after 完成")
            after_path = str(after_file if after_file.suffix else after_file.with_suffix(".jpg"))
            after_jpg = Path(after_path)
            clock.mark("after_verify_start", "看 after 图开始")
            after_verify, after_asset, after_url = _verify_image(
                after_jpg,
                deps=deps,
                profile=profile,
                asset=asset,
                producer="voice_test.run_trial.after",
            )
            clock.mark(
                "after_verify_done",
                "看 after 图完成",
                extra=(after_verify.answer_text if after_verify else ""),
            )
            result, error_reason = _judge(before=before_verify, after=after_verify)
        else:
            result = "INVALID"
            error_reason = "verify_skipped"
    except (VoiceTtsError, WebcamError, VoiceProfileError, BrainCaptureError) as e:
        raise VoiceTestError(str(e)) from e

    return _persist(result, error_reason)


def run_trial_from_params(
    params: dict[str, Any] | None = None,
    *,
    asset: Any = None,
    hooks: TrialHooks | None = None,
) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    try:
        profile = build_profile(params=raw)
    except VoiceProfileError as e:
        raise VoiceTestError(str(e)) from e
    skip_play = str(raw.get("skip_play") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    skip_verify = str(raw.get("skip_verify") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    record = run_trial(
        profile=profile,
        experiment_id=str(raw.get("experiment_id") or "").strip(),
        trial_id=str(raw.get("trial_id") or "").strip(),
        skip_play=skip_play,
        skip_verify=skip_verify,
        asset=asset,
        hooks=hooks,
    )
    summary = (
        f"台灯语音测试 {record['result']}："
        f"voice={profile.voice} speed={profile.speed} volume={profile.volume}"
        f"（{record.get('error_reason') or 'ok'}）"
    )
    outputs = _as_text_map(
        {
            "result": record["result"],
            "answer_text": summary,
            "experiment_id": record["experiment_id"],
            "trial_id": record["trial_id"],
            "verification_result": record["verification_result"],
            "verification_answer": record["verification_answer"],
            "error_reason": record["error_reason"],
            "latency_ms": record["latency_ms"],
            "voice_profile": record["voice_profile"],
            "command": record["command"],
            "asset_ref": record["asset_ref"],
            "before_asset_id": record.get("before_asset_id") or "",
            "after_asset_id": record.get("after_asset_id") or "",
            "playback_label": record.get("playback_label") or "",
            "pickup_text": record.get("pickup_text") or "",
            "speed": record.get("speed"),
            "volume": record.get("volume"),
            "voice": record.get("voice") or "",
            "pitch": record.get("pitch") or "",
            "backend": record.get("backend") or "",
            "settle_ms": record.get("settle_ms"),
            "knobs": record.get("knobs") or {},
            "timeline_text": record.get("timeline_text") or "",
            "wake_word_pause_ms": record.get("wake_word_pause_ms"),
        }
    )
    return summary, outputs
