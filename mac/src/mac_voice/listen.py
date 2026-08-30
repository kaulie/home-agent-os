"""Continuous mic listen: capture thread never blocks on STT.

Lifecycle is self-managed via MAC_VOICE_LISTEN_MODE (always_on / wait_command / wake_word).
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Any

from mac_edge.tts_playback import PlaybackMute
from mac_voice.audio.pickup_ingest import PickupIngestServer
from mac_voice.audio.segmenter import _rms_s16le, iter_utterances
from mac_voice.audio.source import SoundDeviceAudioSource
from mac_voice.audio.types import AudioUtterance, PCM_16K_MONO
from mac_voice.config import VoiceConfig
from mac_voice.edge_id import resolve_parent_edge_id
from mac_voice.mic_lock import acquire_listen_lock
from mac_voice.pipeline import handle_transcript, handle_wake
from mac_voice.stt.base import SpeechToText
from mac_voice.wake import WakeGate

log = logging.getLogger("mac_voice.listen")

# If STT is behind, ignore clips that ended this many seconds ago (wake is ~1s).
_STALE_SEC = 2.5
# Floor for holding the command window after a high-energy chunk. Actual hold
# is max(this, silence_ms + 0.35s) so we do not expire while the segmenter is
# still waiting to cut the command utterance.
_HOLD_AFTER_HIGH_S = 0.75
_HOLD_AFTER_SILENCE_PAD_S = 0.35


def _utterance_duration_ms(utt: AudioUtterance) -> int:
    if utt.speech_start is not None and utt.speech_end is not None:
        return max(0, int((utt.speech_end - utt.speech_start) * 1000))
    pcm = utt.ensure_pcm()
    fmt = utt.format
    denom = fmt.sample_rate * fmt.channels * fmt.sample_width
    if denom <= 0:
        return 0
    return len(pcm) * 1000 // denom


def _utterance_hit_max_speech_cut(utt: AudioUtterance, *, max_speech_ms: int) -> bool:
    return _utterance_duration_ms(utt) >= int(max_speech_ms)


def should_skip_music_idle_stt(
    cfg: VoiceConfig,
    gate: WakeGate | None,
    utt: AudioUtterance,
) -> bool:
    """Skip Volc STT during music playback while wake gate is idle (cost control)."""
    from mac_edge.music_linkage import is_active

    if not is_active():
        return False
    if cfg.listen_mode != "wake_word" or gate is None:
        return False
    if gate.state != "idle":
        return False
    mode = cfg.music_idle_stt
    if mode == "all":
        return False
    duration_ms = _utterance_duration_ms(utt)
    if mode == "none":
        return True
    if _utterance_hit_max_speech_cut(utt, max_speech_ms=cfg.max_speech_ms):
        return True
    return duration_ms > cfg.music_idle_stt_max_ms


class _CaptureActivity:
    """Capture thread → listen loop: do not expire the 5s window mid-utterance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.in_speech = False
        self.last_high_mono = 0.0

    def note(self, state: str) -> None:
        with self._lock:
            if state == "speech":
                self.in_speech = True
            elif state == "idle":
                self.in_speech = False
            if state in ("speech", "high"):
                self.last_high_mono = time.monotonic()

    def should_hold(
        self,
        now: float,
        *,
        queued: int = 0,
        silence_s: float = 1.0,
    ) -> bool:
        if queued > 0:
            return True
        hold_after = max(_HOLD_AFTER_HIGH_S, silence_s + _HOLD_AFTER_SILENCE_PAD_S)
        with self._lock:
            if self.in_speech:
                return True
            return (now - self.last_high_mono) < hold_after


def _put_latest(
    out_q: queue.Queue[AudioUtterance | None],
    utt: AudioUtterance,
) -> None:
    """Never block capture. On overflow, drop pending clips and keep `utt`."""
    try:
        out_q.put_nowait(utt)
        return
    except queue.Full:
        pass
    dropped = 0
    while True:
        try:
            old = out_q.get_nowait()
            if old is not None:
                dropped += 1
        except queue.Empty:
            break
    log.warning(
        "utterance queue full — dropped %d pending, keeping latest (~%d bytes)",
        dropped,
        len(utt.ensure_pcm()),
    )
    try:
        out_q.put_nowait(utt)
    except queue.Full:
        log.warning("utterance dropped (queue still full)")


def _is_stale(utt: AudioUtterance, now: float) -> bool:
    end = utt.speech_end
    if end is None:
        return False
    return (now - end) > _STALE_SEC


def _capture_loop(
    source: SoundDeviceAudioSource,
    cfg: VoiceConfig,
    out_q: queue.Queue[AudioUtterance | None],
    stop: threading.Event,
    activity: _CaptureActivity,
) -> None:
    """Drain mic forever; push silence-cut utterances. Never waits on STT."""
    last_energy_log = 0.0
    peak = 0.0
    try:
        while not stop.is_set():
            try:
                source.open()
                break
            except Exception:
                log.exception("open mic failed; retry in 2s")
                source.close(retry=True)
                if stop.wait(2.0):
                    return
        else:
            return
        mac_pid = resolve_parent_edge_id(cfg)
        chunks = source.iter_pcm()

        def watched() -> Any:
            nonlocal last_energy_log, peak
            for chunk in chunks:
                if stop.is_set():
                    return
                level = _rms_s16le(chunk)
                if level > peak:
                    peak = level
                now = time.time()
                if now - last_energy_log >= 5.0:
                    log.info(
                        "mac_usb alive participant=%s peak_rms=%.0f threshold=%.0f (queue=%d)",
                        mac_pid or "-",
                        peak,
                        cfg.energy_threshold,
                        out_q.qsize(),
                    )
                    peak = 0.0
                    last_energy_log = now
                yield chunk

        start_th = max(cfg.energy_threshold * 2.0, cfg.energy_threshold)

        def watched_levels() -> Any:
            for chunk in watched():
                level = _rms_s16le(chunk)
                if level >= start_th:
                    activity.note("high")
                yield chunk

        # Only mute while local TTS is playing (又咋了 / notify.speak).
        # Music mode must NOT mute: 面条 wake has to work while a song is on.
        # Idle WakeGate still drops non-wake STT (lyrics) so they are not intents.
        tts_mute = PlaybackMute()

        def muted() -> bool:
            return tts_mute()

        for utt in iter_utterances(
            watched_levels(),
            format=PCM_16K_MONO,
            energy_threshold=cfg.energy_threshold,
            start_threshold=start_th,
            silence_ms=cfg.silence_ms,
            min_speech_ms=cfg.min_speech_ms,
            max_speech_ms=cfg.max_speech_ms,
            muted=muted,
            on_activity=activity.note,
        ):
            if stop.is_set():
                break
            # USB mic lives on the Mac Runtime — Input Source = Mac participant_id.
            utt.input_participant_id = mac_pid
            utt.ingress = "mac_usb"
            _put_latest(out_q, utt)
    except Exception:
        log.exception("capture loop died")
    finally:
        try:
            out_q.put_nowait(None)
        except queue.Full:
            pass
        source.close()


def _home_mic_capture_loop(
    ingest: PickupIngestServer,
    cfg: VoiceConfig,
    out_q: queue.Queue[AudioUtterance | None],
    stop: threading.Event,
    activity: _CaptureActivity,
) -> None:
    """Home Mic PCM (via Brain relay) → same utterance queue as USB mic."""
    last_energy_log = 0.0
    peak = 0.0
    # Home Mic AGC raises the noise floor a lot; use a high absolute gate so
    # continuous PCM does not dump 8s noise clips into Volcano STT.
    energy = 4000.0
    start_th = 6500.0
    noise_ema = 800.0
    try:
        chunks = ingest.iter_pcm()

        def watched() -> Any:
            nonlocal last_energy_log, peak, noise_ema
            for chunk in chunks:
                if stop.is_set():
                    return
                level = _rms_s16le(chunk)
                if level > peak:
                    peak = level
                # Track quiet-ish baseline; adapt gate above it.
                if level < max(noise_ema * 1.8, start_th):
                    noise_ema = noise_ema * 0.97 + level * 0.03
                now = time.time()
                if now - last_energy_log >= 5.0:
                    dyn = max(energy, noise_ema * 3.0)
                    log.info(
                        "phone_hap1 alive participant=%s peak_rms=%.0f gate=%.0f noise=%.0f pcm_in=%d (queue=%d)",
                        ingest.participant_id or "-",
                        peak,
                        dyn,
                        noise_ema,
                        ingest.pcm_bytes,
                        out_q.qsize(),
                    )
                    peak = 0.0
                    last_energy_log = now
                yield chunk

        def watched_levels() -> Any:
            for chunk in watched():
                level = _rms_s16le(chunk)
                dyn_start = max(start_th, noise_ema * 4.0)
                if level >= dyn_start:
                    activity.note("high")
                yield chunk

        def dynamic_threshold() -> float:
            return max(energy, noise_ema * 3.0)

        # iter_utterances takes fixed thresholds; approximate with high floor.
        gate_energy = energy
        gate_start = start_th

        for utt in iter_utterances(
            watched_levels(),
            format=PCM_16K_MONO,
            energy_threshold=gate_energy,
            start_threshold=gate_start,
            silence_ms=cfg.silence_ms,
            min_speech_ms=cfg.min_speech_ms,
            max_speech_ms=cfg.max_speech_ms,
            muted=lambda: False,
            on_activity=activity.note,
        ):
            if stop.is_set():
                break
            # Identity = iPhone Runtime participant_id from HAP1 hello (heartbeat registration).
            input_pid = (ingest.participant_id or "").strip()
            log.info(
                "phone_hap1 utterance participant=%s bytes=%d",
                input_pid or "-",
                len(utt.ensure_pcm()),
            )
            utt.input_participant_id = input_pid
            utt.ingress = "phone_hap1"
            _put_latest(out_q, utt)
    except Exception:
        log.exception("home_mic capture loop died")


async def _ack_wake(cfg: VoiceConfig, gate: WakeGate, post_intent: bool) -> None:
    try:
        await asyncio.to_thread(handle_wake, cfg, post=post_intent)
    except Exception:
        log.exception("wake ack local echo failed")
    gate.arm_after_ack()


async def _idle_unimplemented_mode(cfg: VoiceConfig) -> None:
    """Do not silently fall back to always_on or wake_word."""
    log.error(
        "listen_mode=%s is configured but not implemented yet — "
        "mic stays closed (set MAC_VOICE_LISTEN_MODE=wake_word or always_on)",
        cfg.listen_mode,
    )
    while True:
        await asyncio.sleep(60.0)


def _gate_transcript(
    gate: WakeGate | None,
    text: str,
    *,
    speech_start: float | None = None,
    speech_end: float | None = None,
) -> str | None:
    """Return command to post, or None to drop. always_on posts every non-empty line."""
    text = (text or "").strip()
    if gate is None:
        return text or None
    if not text:
        # Still feed so a sticky should_ack from the previous wake is cleared.
        gate.feed("", speech_start=speech_start, speech_end=speech_end)
        return None
    command = gate.feed(text, speech_start=speech_start, speech_end=speech_end)
    if command is None:
        if gate.state == "listening":
            log.info("wake armed hits=%s text=%r", gate.last_hits, text)
        elif gate.state == "acking":
            log.info("wake waiting ack hits=%s text=%r", gate.last_hits, text)
        elif gate.state == "partial":
            log.info("wake partial hits=%s text=%r", gate.last_hits, text)
        else:
            log.info("wake drop state=%s hits=%s text=%r", gate.state, gate.last_hits, text)
        return None
    log.info("wake pass hits=%s command=%r (from %r)", gate.last_hits, command, text)
    return command


async def run_live(
    cfg: VoiceConfig,
    stt: SpeechToText,
    *,
    device: int | str | None,
    post_intent: bool,
) -> None:
    if cfg.listen_mode not in ("always_on", "wake_word"):
        await _idle_unimplemented_mode(cfg)
        return

    listen_lock = acquire_listen_lock(cfg.data_dir / "listen.lock")
    try:
        await _run_live_locked(
            cfg, stt, device=device, post_intent=post_intent
        )
    finally:
        listen_lock.close()


async def _run_live_locked(
    cfg: VoiceConfig,
    stt: SpeechToText,
    *,
    device: int | str | None,
    post_intent: bool,
) -> None:
    gate: WakeGate | None = None
    if cfg.listen_mode == "wake_word":
        gate = WakeGate(
            word=cfg.wake_word,
            repeat=cfg.wake_repeat,
            aliases=cfg.wake_aliases,
            command_window_ms=cfg.command_window_ms,
            partial_wake_ms=cfg.partial_wake_ms,
            double_wake_ms=cfg.double_wake_ms,
        )

    source = SoundDeviceAudioSource(
        device=device if device is not None else cfg.input_device,
        format=PCM_16K_MONO,
        block_ms=100,
        queue_max=500,  # ~50s of 100ms blocks before drop
    )
    utt_q: queue.Queue[AudioUtterance | None] = queue.Queue(maxsize=8)
    stop = threading.Event()
    activity = _CaptureActivity()
    thread = threading.Thread(
        target=_capture_loop,
        args=(source, cfg, utt_q, stop, activity),
        name="mac-voice-capture",
        daemon=True,
    )
    ingest: PickupIngestServer | None = None
    pickup_thread: threading.Thread | None = None
    if cfg.pickup_ingest_enabled:
        ingest = PickupIngestServer(
            host=cfg.pickup_ingest_host,
            port=cfg.pickup_ingest_port,
            chunk_ms=100,
        )
        try:
            ingest.start()
            pickup_thread = threading.Thread(
                target=_home_mic_capture_loop,
                args=(ingest, cfg, utt_q, stop, activity),
                name="mac-voice-home-mic",
                daemon=True,
            )
        except OSError:
            log.exception(
                "home_mic ingest bind failed %s:%s — USB mic only",
                cfg.pickup_ingest_host,
                cfg.pickup_ingest_port,
            )
            ingest = None
    if gate is not None:
        log.info(
            "live listen mode=%s wake=%r x%d window_ms=%s device=%s energy>=%s silence_ms=%s home_mic=%s (Ctrl+C to stop)",
            cfg.listen_mode,
            cfg.wake_word,
            cfg.wake_repeat,
            cfg.command_window_ms,
            device if device is not None else cfg.input_device,
            cfg.energy_threshold,
            cfg.silence_ms,
            "on" if ingest is not None else "off",
        )
    else:
        log.info(
            "live listen mode=%s device=%s energy>=%s silence_ms=%s home_mic=%s (Ctrl+C to stop)",
            cfg.listen_mode,
            device if device is not None else cfg.input_device,
            cfg.energy_threshold,
            cfg.silence_ms,
            "on" if ingest is not None else "off",
        )
    thread.start()
    if pickup_thread is not None:
        pickup_thread.start()
    wake_task: asyncio.Task[None] | None = None
    try:
        while True:
            try:
                utt = await asyncio.to_thread(utt_q.get, True, 0.4)
            except queue.Empty:
                if gate is not None:
                    reason = gate.expire_if_needed(
                        hold=activity.should_hold(
                            time.monotonic(),
                            queued=utt_q.qsize(),
                            silence_s=cfg.silence_ms / 1000.0,
                        )
                    )
                    if reason:
                        log.info(
                            "wake %s — no command utterance in window_ms=%s",
                            reason,
                            cfg.command_window_ms,
                        )
                continue
            if utt is None:
                break
            input_pid = (utt.input_participant_id or "").strip()
            ingress = (utt.ingress or "").strip() or "-"
            now = time.monotonic()
            if _is_stale(utt, now):
                log.info(
                    "skip stale utterance input=%s ingress=%s age=%.1fs bytes=%d",
                    input_pid or "-",
                    ingress,
                    now - (utt.speech_end or now),
                    len(utt.ensure_pcm()),
                )
                continue
            log.info(
                "STT start input=%s ingress=%s bytes=%d",
                input_pid or "-",
                ingress,
                len(utt.ensure_pcm()),
            )
            if should_skip_music_idle_stt(cfg, gate, utt):
                duration_ms = _utterance_duration_ms(utt)
                log.info(
                    "skip STT music_idle mode=%s duration_ms=%s",
                    cfg.music_idle_stt,
                    duration_ms,
                )
                continue
            try:
                text = await stt.transcribe(utt)
            except asyncio.TimeoutError:
                log.error(
                    "STT timed out input=%s ingress=%s bytes=%d",
                    input_pid or "-",
                    ingress,
                    len(utt.ensure_pcm()),
                )
                continue
            except Exception as e:
                log.error("STT failed input=%s ingress=%s: %s", input_pid or "-", ingress, e)
                continue
            log.info(
                "STT text=%r input=%s ingress=%s",
                text,
                input_pid or "-",
                ingress,
            )
            command = _gate_transcript(
                gate,
                text,
                speech_start=utt.speech_start,
                speech_end=utt.speech_end,
            )
            if gate is not None and gate.consume_ack():
                if wake_task is not None and not wake_task.done():
                    wake_task.cancel()
                wake_task = asyncio.create_task(_ack_wake(cfg, gate, post_intent))
            if command is None:
                continue
            handle_transcript(
                cfg,
                command,
                post=post_intent,
                input_participant_id=input_pid,
                ingress=utt.ingress,
            )
    finally:
        if wake_task is not None and not wake_task.done():
            wake_task.cancel()
        stop.set()
        if ingest is not None:
            ingest.stop()
        source.close()
        thread.join(timeout=2.0)
        if pickup_thread is not None:
            pickup_thread.join(timeout=2.0)
