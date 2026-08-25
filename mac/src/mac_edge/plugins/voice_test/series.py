"""Phase 2: repeat one VoiceProfile N times and summarize k/N.

Loop lives here (CLI / orchestrator), not in Runtime or the planner.

``wake_word_pause_ms`` (小书小书 → 打开台灯 / 关闭台灯) is a first-class
sweep variable, distinct from ``settle_ms`` (after command, before photo)
and CLI ``--gap-ms`` (between trials).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any

from mac_edge.plugins.voice_test.profile import VoiceProfile, pause_window_risk
from mac_edge.plugins.voice_test.store import experiments_dir
from mac_edge.plugins.voice_test.trial import VoiceTestError, run_trial
from mac_edge.plugins.voice_test.tts import play_audio, prepare_utterance

log = logging.getLogger("mac_edge.voice_test.series")

VALID = frozenset({"SUCCESS", "FAIL"})
OFF_COMMAND = "关闭台灯"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def parse_int_list(
    raw: str,
    *,
    name: str,
    lo: int,
    hi: int,
) -> list[int]:
    text = (raw or "").strip()
    if not text:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for part in text.replace(";", ",").split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            value = int(float(piece))
        except ValueError as e:
            raise VoiceTestError(f"{name} 不是整数：{piece!r}") from e
        if value < lo or value > hi:
            raise VoiceTestError(f"{name}={value} 超出范围 {lo}–{hi}")
        if value not in seen:
            seen.add(value)
            out.append(value)
    if not out:
        raise VoiceTestError(f"{name} 列表为空")
    return out


def parse_pause_ms_list(raw: str) -> list[int]:
    """Parse ``800,1500,2000`` into unique pause values (keep order)."""
    return parse_int_list(raw, name="wake_word_pause_ms", lo=0, hi=15_000)


def parse_csv_list(raw: str, *, name: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in text.replace(";", ",").split(","):
        piece = part.strip()
        if not piece:
            continue
        key = piece.casefold()
        if key not in seen:
            seen.add(key)
            out.append(piece)
    if not out:
        raise VoiceTestError(f"{name} 列表为空")
    return out


def parse_float_list(
    raw: str,
    *,
    name: str,
    lo: float,
    hi: float,
) -> list[float]:
    text = (raw or "").strip()
    if not text:
        return []
    out: list[float] = []
    seen: set[float] = set()
    for part in text.replace(";", ",").split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            value = float(piece)
        except ValueError as e:
            raise VoiceTestError(f"{name} 不是数字：{piece!r}") from e
        if value < lo or value > hi:
            raise VoiceTestError(f"{name}={value} 超出范围 {lo}–{hi}")
        key = round(value, 4)
        if key not in seen:
            seen.add(key)
            out.append(value)
    if not out:
        raise VoiceTestError(f"{name} 列表为空")
    return out


def _num_of(rec: dict[str, Any], *keys: str) -> float | None:
    vp = rec.get("voice_profile") if isinstance(rec.get("voice_profile"), dict) else {}
    knobs = rec.get("knobs") if isinstance(rec.get("knobs"), dict) else {}
    for key in keys:
        for blob in (rec, knobs, vp):
            if not isinstance(blob, dict) or blob.get(key) is None or blob.get(key) == "":
                continue
            try:
                return float(blob[key])
            except (TypeError, ValueError):
                continue
    return None


def _str_of(rec: dict[str, Any], *keys: str) -> str | None:
    vp = rec.get("voice_profile") if isinstance(rec.get("voice_profile"), dict) else {}
    knobs = rec.get("knobs") if isinstance(rec.get("knobs"), dict) else {}
    for key in keys:
        for blob in (rec, knobs, vp):
            if not isinstance(blob, dict) or key not in blob:
                continue
            raw = blob.get(key)
            if raw is None:
                continue
            return str(raw).strip()
    return None


def _group_by_str(
    records: list[dict[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        value = _str_of(rec, key)
        if value is None:
            continue
        label = value or "default"
        groups.setdefault(label, []).append(rec)
    out: dict[str, dict[str, Any]] = {}
    for label, group in groups.items():
        cell = summarize_records_flat(group)
        out[label] = {
            key: label,
            "success_over_valid": cell["success_over_valid"],
            "success_rate": cell["success_rate"],
            "n": cell["n"],
            "valid": cell["valid"],
        }
    return out


def _group_by_num(
    records: list[dict[str, Any]], *keys: str
) -> dict[str, dict[str, Any]]:
    groups: dict[float, list[dict[str, Any]]] = {}
    for rec in records:
        value = _num_of(rec, *keys)
        if value is None:
            continue
        groups.setdefault(value, []).append(rec)
    out: dict[str, dict[str, Any]] = {}
    for value, group in sorted(groups.items()):
        cell = summarize_records_flat(group)
        label = str(value)
        out[label] = {
            keys[0]: value,
            "success_over_valid": cell["success_over_valid"],
            "success_rate": cell["success_rate"],
            "n": cell["n"],
            "valid": cell["valid"],
        }
    return out


def _wake_reply_over(records: list[dict[str, Any]]) -> str:
    yes = 0
    known = 0
    for rec in records:
        heard = rec.get("wake_reply_heard")
        if heard is None:
            blob = rec.get("wake_reply")
            if isinstance(blob, dict):
                heard = blob.get("heard")
        if heard is True:
            yes += 1
            known += 1
        elif heard is False:
            known += 1
    return f"{yes}/{known}" if known else "0/0"


def summarize_records_flat(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for rec in records:
        key = str(rec.get("result") or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    valid = [r for r in records if r.get("result") in VALID]
    success = sum(1 for r in valid if r.get("result") == "SUCCESS")
    rate = (success / len(valid)) if valid else None
    return {
        "n": len(records),
        "valid": len(valid),
        "success": success,
        "fail": sum(1 for r in valid if r.get("result") == "FAIL"),
        "invalid": counts.get("INVALID", 0),
        "infra": counts.get("INFRA", 0),
        "success_rate": None if rate is None else round(rate, 4),
        "success_over_valid": f"{success}/{len(valid)}" if valid else "0/0",
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for rec in records:
        key = str(rec.get("result") or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    valid = [r for r in records if r.get("result") in VALID]
    success = sum(1 for r in valid if r.get("result") == "SUCCESS")
    fail = sum(1 for r in valid if r.get("result") == "FAIL")
    heard_ok = 0
    heard_n = 0
    latencies: list[int] = []
    for rec in records:
        lat = rec.get("latency_ms")
        if isinstance(lat, int):
            latencies.append(lat)
        for key in ("wake_loopback", "command_loopback"):
            blob = rec.get(key)
            if not isinstance(blob, dict):
                continue
            heard_n += 1
            if blob.get("heard") is True:
                heard_ok += 1
    rate = (success / len(valid)) if valid else None
    pause_groups: dict[int, list[dict[str, Any]]] = {}
    for rec in records:
        pause = _num_of(rec, "wake_word_pause_ms")
        if pause is None:
            continue
        pause_groups.setdefault(int(pause), []).append(rec)
    by_pause: dict[str, dict[str, Any]] = {}
    for pause, group in sorted(pause_groups.items()):
        cell = summarize_records_flat(group)
        by_pause[str(pause)] = {
            "wake_word_pause_ms": pause,
            "pause_risk": pause_window_risk(pause),
            "lamp_success_over_valid": cell["success_over_valid"],
            "success_over_valid": cell["success_over_valid"],
            "wake_reply_over_n": _wake_reply_over(group),
            "success_rate": cell["success_rate"],
            "n": cell["n"],
            "valid": cell["valid"],
        }
    cell_groups: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        pause = _num_of(rec, "wake_word_pause_ms")
        speed = _num_of(rec, "speed")
        volume = _num_of(rec, "volume")
        settle = _num_of(rec, "settle_ms")
        voice = _str_of(rec, "voice")
        backend = _str_of(rec, "backend")
        pitch = _str_of(rec, "pitch")
        if pause is None or speed is None or volume is None:
            continue
        key = (
            f"voice={voice or '-'},backend={backend or '-'},"
            f"speed={speed},volume={volume},pause={int(pause)},"
            f"settle={int(settle) if settle is not None else '-'},"
            f"pitch={pitch or 'default'}"
        )
        cell_groups.setdefault(key, []).append(rec)
    by_cell: dict[str, dict[str, Any]] = {}
    for key, group in cell_groups.items():
        cell = summarize_records_flat(group)
        by_cell[key] = {
            "success_over_valid": cell["success_over_valid"],
            "n": cell["n"],
            "valid": cell["valid"],
        }
    return {
        "n": len(records),
        "valid": len(valid),
        "success": success,
        "fail": fail,
        "invalid": counts.get("INVALID", 0),
        "infra": counts.get("INFRA", 0),
        "counts": counts,
        "success_rate": None if rate is None else round(rate, 4),
        "success_over_valid": f"{success}/{len(valid)}" if valid else "0/0",
        "loopback_heard": f"{heard_ok}/{heard_n}" if heard_n else "0/0",
        "wake_reply_over_n": _wake_reply_over(records),
        "mean_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "by_pause_ms": by_pause,
        "by_speed": _group_by_num(records, "speed"),
        "by_volume": _group_by_num(records, "volume"),
        "by_voice": _group_by_str(records, "voice"),
        "by_backend": _group_by_str(records, "backend"),
        "by_pitch": _group_by_str(records, "pitch"),
        "by_settle_ms": _group_by_num(records, "settle_ms"),
        "by_cell": by_cell,
    }


def reset_lamp_off(profile: VoiceProfile, *, work: Path) -> None:
    """Speak wake + 关闭台灯 so the next trial is not INVALID. Not a scored trial.

    Uses the same ``wake_word_pause_ms`` as the scored command (the variable
    under test).
    """
    work.mkdir(parents=True, exist_ok=True)
    wake_path = prepare_utterance(
        profile.wake_word,
        work / "reset_wake",
        profile=profile,
        clip_path=profile.wake_audio,
    )
    off_path = prepare_utterance(
        OFF_COMMAND, work / "reset_off", profile=profile
    )
    play_audio(
        wake_path,
        volume=profile.volume,
        confirm=profile.confirm_playback,
        heard_wav=wake_path.with_name(wake_path.stem + ".heard.wav"),
    )
    if profile.wake_word_pause_ms:
        time.sleep(profile.wake_word_pause_ms / 1000.0)
    play_audio(
        off_path,
        volume=profile.volume,
        confirm=profile.confirm_playback,
        heard_wav=off_path.with_name(off_path.stem + ".heard.wav"),
        skip_ambient=True,
    )
    time.sleep(max(profile.settle_ms, 1500) / 1000.0)


def _run_n(
    *,
    profile: VoiceProfile,
    n: int,
    experiment_id: str,
    gap_ms: int,
    skip_play: bool,
    skip_verify: bool,
    reset_on_success: bool,
    index_offset: int,
) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    stopped_reason = ""
    for i in range(n):
        log.info(
            "voice_test series %s voice=%s backend=%s speed=%s volume=%s pause=%sms settle=%sms trial %s/%s",
            experiment_id,
            profile.voice,
            profile.backend,
            profile.speed,
            profile.volume,
            profile.wake_word_pause_ms,
            profile.settle_ms,
            i + 1,
            n,
        )
        try:
            rec = run_trial(
                profile=profile,
                experiment_id=experiment_id,
                skip_play=skip_play,
                skip_verify=skip_verify,
            )
        except VoiceTestError as e:
            rec = {
                "experiment_id": experiment_id,
                "trial_id": "",
                "result": "INFRA",
                "error_reason": str(e),
                "latency_ms": 0,
                "wake_word_pause_ms": profile.wake_word_pause_ms,
                "settle_ms": profile.settle_ms,
                "speed": profile.speed,
                "volume": profile.volume,
                "voice": profile.voice,
                "backend": profile.backend,
                "pitch": profile.pitch,
                "voice_profile": profile.to_dict(),
                "knobs": {
                    "backend": profile.backend,
                    "voice": profile.voice,
                    "speed": profile.speed,
                    "volume": profile.volume,
                    "pitch": profile.pitch,
                    "wake_word_pause_ms": profile.wake_word_pause_ms,
                    "settle_ms": profile.settle_ms,
                },
            }
            records.append(rec)
            # Volume too quiet is a measured cell, not a reason to drop the grid.
            if "扬声器没有被麦克风听到" in str(e):
                log.warning("loopback miss on this cell, continue grid: %s", e)
                if i + 1 < n and gap_ms > 0:
                    time.sleep(gap_ms / 1000.0)
                continue
            return records, f"infra:{e}"
        rec["series_index"] = index_offset + i + 1
        rec["wake_word_pause_ms"] = profile.wake_word_pause_ms
        records.append(rec)
        if rec.get("result") == "INVALID" and rec.get("error_reason") == "lamp_already_on":
            return records, "lamp_already_on"
        if rec.get("result") == "SUCCESS" and reset_on_success and not skip_play:
            try:
                reset_lamp_off(
                    profile, work=experiments_dir() / experiment_id / "reset"
                )
            except Exception as e:  # noqa: BLE001 — next trial will INVALID if still on
                log.warning("reset 关闭台灯 failed: %s", e)
                return records, f"reset_failed:{e}"
        if i + 1 < n and gap_ms > 0:
            time.sleep(gap_ms / 1000.0)
    return records, stopped_reason


def run_series(
    *,
    profile: VoiceProfile,
    n: int,
    experiment_id: str = "",
    gap_ms: int = 3000,
    skip_play: bool = False,
    skip_verify: bool = False,
    reset_on_success: bool = True,
    pause_ms_list: list[int] | None = None,
    speed_list: list[float] | None = None,
    volume_list: list[float] | None = None,
    voice_list: list[str] | None = None,
    backend_list: list[str] | None = None,
    pitch_list: list[str] | None = None,
    settle_ms_list: list[int] | None = None,
) -> dict[str, Any]:
    if n < 1:
        raise VoiceTestError("repeat N 必须 >= 1")
    eid = (experiment_id or "").strip() or _new_id()
    pauses = list(pause_ms_list) if pause_ms_list else [profile.wake_word_pause_ms]
    speeds = list(speed_list) if speed_list else [profile.speed]
    volumes = list(volume_list) if volume_list else [profile.volume]
    voices = list(voice_list) if voice_list else [profile.voice]
    backends = list(backend_list) if backend_list else [profile.backend]
    pitches = list(pitch_list) if pitch_list else [profile.pitch]
    settles = list(settle_ms_list) if settle_ms_list else [profile.settle_ms]
    records: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    stopped_reason = ""
    grid = list(product(pauses, speeds, volumes, voices, backends, pitches, settles))
    for idx, (pause, speed, volume, voice, backend, pitch, settle) in enumerate(grid):
        cell_profile = replace(
            profile,
            wake_word_pause_ms=int(pause),
            speed=float(speed),
            volume=float(volume),
            voice=str(voice),
            backend=str(backend),
            pitch=str(pitch),
            settle_ms=int(settle),
        )
        cell_recs, stopped_reason = _run_n(
            profile=cell_profile,
            n=n,
            experiment_id=eid,
            gap_ms=gap_ms,
            skip_play=skip_play,
            skip_verify=skip_verify,
            reset_on_success=reset_on_success,
            index_offset=len(records),
        )
        records.extend(cell_recs)
        cells.append(
            {
                "wake_word_pause_ms": int(pause),
                "speed": float(speed),
                "volume": float(volume),
                "voice": str(voice),
                "backend": str(backend),
                "pitch": str(pitch),
                "settle_ms": int(settle),
                "summary": summarize_records_flat(cell_recs),
                "stopped_reason": stopped_reason,
            }
        )
        if stopped_reason:
            break
        if idx + 1 < len(grid) and gap_ms > 0:
            time.sleep(gap_ms / 1000.0)
    summary = summarize_records(records)
    payload = {
        "experiment_id": eid,
        "profile": profile.to_dict(),
        "requested_per_cell": n,
        "pause_ms_list": pauses,
        "speed_list": speeds,
        "volume_list": volumes,
        "voice_list": voices,
        "backend_list": backends,
        "pitch_list": pitches,
        "settle_ms_list": settles,
        "requested": n * len(grid),
        "completed": len(records),
        "stopped_reason": stopped_reason,
        "summary": summary,
        "cells": cells,
        "trials": records,
    }
    out = experiments_dir() / eid / "series.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["store_path"] = str(out)
    return payload
