"""Create SpeechToText from config."""

from __future__ import annotations

from mac_voice.config import VoiceConfig
from mac_voice.stt.base import SpeechToText
from mac_voice.stt.volc_sauc import VolcengineSaucSTT


def create_stt(cfg: VoiceConfig) -> SpeechToText:
    provider = (cfg.stt_provider or "volc_sauc").strip().lower()
    if provider == "volc_sauc":
        if not cfg.sauc_api_key and not (cfg.sauc_app_key and cfg.sauc_access_key):
            raise ValueError(
                "MAC_VOICE_SAUC_API_KEY (or APP_KEY+ACCESS_KEY) required for volc_sauc"
            )
        return VolcengineSaucSTT(
            api_key=cfg.sauc_api_key,
            url=cfg.sauc_url,
            resource_id=cfg.sauc_resource_id,
            seg_duration_ms=cfg.sauc_seg_duration_ms,
            app_key=cfg.sauc_app_key,
            access_key=cfg.sauc_access_key,
        )
    raise ValueError(f"Unknown MAC_VOICE_STT_PROVIDER={provider!r} (supported: volc_sauc)")
