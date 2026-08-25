"""CLI: one Phase-1 trial without going through Brain as the experiment runner.

Capture defaults to iPhone ``camera.capture`` via Brain (not FaceTime).

  PYTHONPATH=src python -m mac_edge.plugins.voice_test --once --skip-play
  PYTHONPATH=src python -m mac_edge.plugins.voice_test --repeat 5
  PYTHONPATH=src python -m mac_edge.plugins.voice_test --repeat 3 --voices Tingting,Mei-Jia --pauses 800,1500 --speeds 0.8,1.0 --volumes 0.6,0.8
  PYTHONPATH=src python -m mac_edge.plugins.voice_test --capture-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mac_edge.plugins.voice_test.profile import (
    RECOMMENDED_BACKENDS,
    RECOMMENDED_PAUSE_MS,
    RECOMMENDED_PITCHES,
    RECOMMENDED_SETTLE_MS,
    RECOMMENDED_SPEEDS,
    RECOMMENDED_VOICES,
    RECOMMENDED_VOLUMES,
    build_profile,
)
from mac_edge.plugins.voice_test.series import (
    parse_csv_list,
    parse_float_list,
    parse_int_list,
    parse_pause_ms_list,
    run_series,
)
from mac_edge.plugins.voice_test.trial import VoiceTestError, run_trial
from mac_edge.plugins.voice_test.tts import generate_speech, play_audio


def _load_mac_dotenv() -> None:
    path = Path(__file__).resolve().parents[4] / ".env"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
from mac_edge.plugins.voice_test.webcam import WebcamError, capture_still


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Voice lamp-control trial (Phase 1)")
    p.add_argument("--once", action="store_true", help="full trial: play + capture + verify")
    p.add_argument(
        "--repeat",
        type=int,
        default=0,
        metavar="N",
        help="run N trials with the same VoiceProfile; print k/N (Phase 2)",
    )
    p.add_argument(
        "--gap-ms",
        type=int,
        default=3000,
        help="pause between repeated trials (default 3000)",
    )
    p.add_argument("--experiment-id", default="", dest="experiment_id")
    p.add_argument("--audio-only", action="store_true", help="generate and play, no camera")
    p.add_argument("--capture-only", action="store_true", help="webcam still only")
    p.add_argument("--dry-run", action="store_true", help="play a non-command phrase; skip verify")
    p.add_argument("--skip-verify", action="store_true", help="do not call vision.ask")
    p.add_argument("--skip-play", action="store_true", help="do not speak; only capture+verify")
    p.add_argument(
        "--probe-play",
        action="store_true",
        help="play 语音测试 and require USB-mic loopback to hear it",
    )
    p.add_argument(
        "--capture",
        default="",
        help="gopro (camera.capture via Brain, default) | webcam",
    )
    p.add_argument("--profile", default="", help="VoiceProfile yaml/json path")
    p.add_argument("--voice", default="")
    p.add_argument("--speed", default="")
    p.add_argument("--volume", default="")
    p.add_argument("--pitch", default="")
    p.add_argument("--backend", default="")
    p.add_argument(
        "--settle-ms",
        default="",
        dest="settle_ms",
        help="wait after command before after-photo (ms). Not wake-command pause.",
    )
    p.add_argument("--command", default="")
    p.add_argument("--wake-word", default="", dest="wake_word")
    p.add_argument(
        "--wake-pause-ms",
        default="",
        dest="wake_pause_ms",
        help="pause between 小书小书 and 打开台灯/关闭台灯 (ms). Not --gap-ms.",
    )
    p.add_argument(
        "--pauses",
        default="",
        help="sweep wake-command gaps, e.g. 500,800,1500,2000 or 'recommended'; --repeat is per cell",
    )
    p.add_argument(
        "--speeds",
        default="",
        help="sweep TTS speed, e.g. 0.8,1.0,1.2 or 'recommended'",
    )
    p.add_argument(
        "--volumes",
        default="",
        help="sweep afplay volume, e.g. 0.6,0.8,1.0 or 'recommended'",
    )
    p.add_argument(
        "--voices",
        default="",
        help="sweep TTS voice, e.g. Tingting,Mei-Jia or 'recommended'",
    )
    p.add_argument(
        "--backends",
        default="",
        help="sweep TTS engine, e.g. say,edge or 'recommended'",
    )
    p.add_argument(
        "--pitches",
        default="",
        help="sweep pitch (edge-tts only), e.g. +0Hz,+10Hz,-10Hz or 'recommended'",
    )
    p.add_argument(
        "--settles",
        default="",
        help="sweep settle_ms after command before photo, e.g. 1000,1500,2000 or 'recommended'",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _load_mac_dotenv()
    args = _parser().parse_args(argv)
    params: dict[str, str] = {}
    if args.voice:
        params["voice"] = args.voice
    if args.speed:
        params["speed"] = args.speed
    if args.volume:
        params["volume"] = args.volume
    if args.pitch:
        params["pitch"] = args.pitch
    if args.backend:
        params["backend"] = args.backend
    if args.settle_ms:
        params["settle_ms"] = args.settle_ms
    if args.command:
        params["command"] = args.command
    if args.wake_word:
        params["wake_word"] = args.wake_word
    if args.wake_pause_ms:
        params["wake_word_pause_ms"] = args.wake_pause_ms
    if args.capture:
        params["capture_backend"] = args.capture
    if args.skip_play:
        params["skip_play"] = "true"
    profile_path = Path(args.profile).expanduser() if args.profile else None
    profile = build_profile(file_path=profile_path, params=params)

    if args.capture_only:
        dest = Path("/tmp/voice_test_capture.jpg")
        try:
            if profile.capture_backend == "gopro":
                from mac_edge.plugins.voice_test.brain_capture import capture_still as gopro_capture

                gopro_capture(dest)
            else:
                from mac_edge.plugins.voice_test.webcam import capture_still

                capture_still(dest, device=profile.webcam_device)
        except Exception as e:
            print(f"FAIL capture: {e}", file=sys.stderr)
            return 2
        print(f"captured {dest} ({dest.stat().st_size} bytes) backend={profile.capture_backend}")
        return 0

    if args.probe_play:
        dest = Path("/tmp/voice_test_probe")
        try:
            audio = generate_speech("语音测试", dest, profile=profile)
            result = play_audio(
                audio,
                volume=profile.volume,
                confirm=True,
                heard_wav=Path("/tmp/voice_test_probe.heard.wav"),
            )
        except Exception as e:
            print(f"FAIL playback: {e}", file=sys.stderr)
            return 2
        print(json.dumps(result.to_dict() if result else {"heard": None}, ensure_ascii=False, indent=2))
        return 0 if result and result.heard else 2

    if args.audio_only or args.dry_run:
        text = "语音测试" if args.dry_run else profile.command
        dest = Path("/tmp/voice_test_phrase")
        try:
            audio = generate_speech(text, dest, profile=profile)
            play_audio(
                audio,
                volume=profile.volume,
                confirm=bool(args.dry_run or profile.confirm_playback),
            )
        except Exception as e:
            print(f"FAIL audio: {e}", file=sys.stderr)
            return 2
        print(f"played {audio} text={text!r} voice={profile.voice} speed={profile.speed} volume={profile.volume}")
        return 0

    pause_ms_list: list[int] | None = None
    speed_list: list[float] | None = None
    volume_list: list[float] | None = None
    voice_list: list[str] | None = None
    backend_list: list[str] | None = None
    pitch_list: list[str] | None = None
    settle_ms_list: list[int] | None = None
    if args.pauses:
        raw_pauses = str(args.pauses).strip().lower()
        if raw_pauses in ("recommended", "default"):
            pause_ms_list = list(RECOMMENDED_PAUSE_MS)
        else:
            try:
                pause_ms_list = parse_pause_ms_list(args.pauses)
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
    if args.speeds:
        raw_speeds = str(args.speeds).strip().lower()
        if raw_speeds in ("recommended", "default"):
            speed_list = list(RECOMMENDED_SPEEDS)
        else:
            try:
                speed_list = parse_float_list(args.speeds, name="speed", lo=0.5, hi=2.0)
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
    if args.volumes:
        raw_vols = str(args.volumes).strip().lower()
        if raw_vols in ("recommended", "default"):
            volume_list = list(RECOMMENDED_VOLUMES)
        else:
            try:
                volume_list = parse_float_list(args.volumes, name="volume", lo=0.0, hi=1.0)
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
    if args.voices:
        raw_voices = str(args.voices).strip().lower()
        if raw_voices in ("recommended", "default"):
            voice_list = list(RECOMMENDED_VOICES)
        else:
            try:
                voice_list = parse_csv_list(args.voices, name="voice")
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
    if args.backends:
        raw_backends = str(args.backends).strip().lower()
        if raw_backends in ("recommended", "default"):
            backend_list = list(RECOMMENDED_BACKENDS)
        else:
            try:
                backend_list = [b.lower() for b in parse_csv_list(args.backends, name="backend")]
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
            bad = [b for b in backend_list if b not in ("say", "edge")]
            if bad:
                print(f"FAIL series: backend 只支持 say|edge，收到 {bad}", file=sys.stderr)
                return 2
    if args.pitches:
        raw_pitches = str(args.pitches).strip().lower()
        if raw_pitches in ("recommended", "default"):
            pitch_list = list(RECOMMENDED_PITCHES)
        else:
            try:
                pitch_list = parse_csv_list(args.pitches, name="pitch")
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2
    if args.settles:
        raw_settles = str(args.settles).strip().lower()
        if raw_settles in ("recommended", "default"):
            settle_ms_list = list(RECOMMENDED_SETTLE_MS)
        else:
            try:
                settle_ms_list = parse_int_list(
                    args.settles, name="settle_ms", lo=0, hi=15_000
                )
            except VoiceTestError as e:
                print(f"FAIL series: {e}", file=sys.stderr)
                return 2

    n = int(args.repeat) if args.repeat and args.repeat > 0 else 0
    sweeping = bool(
        pause_ms_list
        or speed_list
        or volume_list
        or voice_list
        or backend_list
        or pitch_list
        or settle_ms_list
    )
    if n <= 0 and (args.once or sweeping):
        n = 1
    if n <= 0:
        _parser().print_help()
        return 1

    single = n == 1 and not args.experiment_id and not sweeping
    if single:
        try:
            record = run_trial(
                profile=profile,
                skip_play=bool(args.skip_play),
                skip_verify=bool(args.skip_verify or args.dry_run),
            )
        except VoiceTestError as e:
            print(f"FAIL trial: {e}", file=sys.stderr)
            return 2
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0 if record.get("result") != "INVALID" or args.skip_verify else 0

    try:
        payload = run_series(
            profile=profile,
            n=n,
            experiment_id=args.experiment_id,
            gap_ms=max(0, int(args.gap_ms)),
            skip_play=bool(args.skip_play),
            skip_verify=bool(args.skip_verify or args.dry_run),
            pause_ms_list=pause_ms_list,
            speed_list=speed_list,
            volume_list=volume_list,
            voice_list=voice_list,
            backend_list=backend_list,
            pitch_list=pitch_list,
            settle_ms_list=settle_ms_list,
        )
    except VoiceTestError as e:
        print(f"FAIL series: {e}", file=sys.stderr)
        return 2
    summary = payload.get("summary") or {}
    def _rates(blob: dict) -> dict:
        return {
            k: (v or {}).get("success_over_valid") for k, v in (blob or {}).items()
        }

    print(
        "SERIES experiment={eid} success={rate} by_voice={voice} by_pause={pause} "
        "by_speed={speed} by_volume={vol} by_backend={backend} by_pitch={pitch} "
        "by_settle={settle} heard={heard} mean_ms={ms} stopped={why}".format(
            eid=payload.get("experiment_id"),
            rate=summary.get("success_over_valid"),
            voice=_rates(summary.get("by_voice") or {}),
            pause=_rates(summary.get("by_pause_ms") or {}),
            speed=_rates(summary.get("by_speed") or {}),
            vol=_rates(summary.get("by_volume") or {}),
            backend=_rates(summary.get("by_backend") or {}),
            pitch=_rates(summary.get("by_pitch") or {}),
            settle=_rates(summary.get("by_settle_ms") or {}),
            heard=summary.get("loopback_heard"),
            ms=summary.get("mean_latency_ms"),
            why=payload.get("stopped_reason") or "-",
        ),
        file=sys.stderr,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if int(summary.get("infra") or 0) > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
