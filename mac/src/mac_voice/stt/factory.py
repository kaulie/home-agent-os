"""Create SpeechToText from config."""

from __future__ import annotations

from mac_voice.config import VoiceConfig
from mac_voice.stt.base import SpeechToText
from mac_voice.stt.volc_sauc import VolcengineSaucSTT
from mac_voice.stt.wav_store import SttWavStore


def create_stt(cfg: VoiceConfig) -> SpeechToText:
    provider = (cfg.stt_provider or "volc_sauc").strip().lower()
    if provider == "volc_sauc":
        if not cfg.sauc_api_key and not (cfg.sauc_app_key and cfg.sauc_access_key):
            raise ValueError(
                "MAC_VOICE_SAUC_API_KEY (or APP_KEY+ACCESS_KEY) required for volc_sauc"
            )
        store = SttWavStore(
            directory=cfg.stt_wav_dir,
            keep=cfg.stt_wav_keep,
            max_age_hours=cfg.stt_wav_max_age_hours,
            max_files=cfg.stt_wav_max_files,
            max_mb=cfg.stt_wav_max_mb,
        )
        if store.directory is not None:
            store.ensure_dir()
        return VolcengineSaucSTT(
            api_key=cfg.sauc_api_key,
            url=cfg.sauc_url,
            resource_id=cfg.sauc_resource_id,
            seg_duration_ms=cfg.sauc_seg_duration_ms,
            app_key=cfg.sauc_app_key,
            access_key=cfg.sauc_access_key,
            wav_store=store,
        )
    raise ValueError(f"Unknown MAC_VOICE_STT_PROVIDER={provider!r} (supported: volc_sauc)")
