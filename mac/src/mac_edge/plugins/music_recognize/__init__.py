"""Mac Edge capability: music.recognize (listen-to-identify ambient music).

Records a continuous 10–30 s window from the room mic and identifies which song
is playing via a pluggable recognition Provider (mock | audd | acrcloud | shazam).
The result is returned as an `answer_text` sentence which Brain plays back on the
issuing device (Source Affinity). Single song per session; hit or 30 s timeout
exits the session.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from mac_edge.plugins.music_recognize.config import (
    PROVIDER_NONE,
    MusicRecognizeConfig,
    load_config,
    provider_selected,
)
from mac_edge.plugins.music_recognize.errors import (
    MusicCaptureError,
    MusicRecognizeError,
)
from mac_edge.plugins.music_recognize.providers import (
    ProviderError,
    ProviderNotConfiguredError,
    build_provider,
)

log = logging.getLogger("mac_edge.music_recognize")

__all__ = [
    "MusicRecognizeError",
    "MusicCaptureError",
    "configured",
    "run_from_params",
    "dispatch",
]


def configured() -> bool:
    """Whether this Mac should advertise music.recognize (provider usable)."""
    return provider_selected()


def run_from_params(
    params: dict[str, Any] | None = None,
    *,
    cfg: MusicRecognizeConfig | None = None,
    iter_pcm: Iterable[bytes] | None = None,
    provider: Callable[[bytes], Any] | None = None,
    pcm_to_wav_fn: Callable[[bytes], bytes] | None = None,
    session_tag: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Execute one recognition session; returns (msg, outputs)."""
    _ = params or {}
    cfg = cfg or load_config()
    if not cfg.provider or cfg.provider == PROVIDER_NONE or not provider_selected():
        raise MusicRecognizeError(
            "识曲服务未配置：需要先设置 MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER"
            "（mock/audd/acrcloud/shazam）及对应密钥"
        )
    if provider is None:
        try:
            provider = build_provider(cfg)
        except ProviderNotConfiguredError as e:
            raise MusicRecognizeError(str(e)) from e

    from mac_edge.plugins.music_recognize.capture import iter_mic_pcm
    from mac_edge.plugins.music_recognize.orchestrate import run_session
    from mac_edge.plugins.music_recognize.wav import pcm_to_wav as default_pcm_to_wav

    stream = iter_pcm if iter_pcm is not None else iter_mic_pcm(cfg.input_device)
    wav_fn = pcm_to_wav_fn or default_pcm_to_wav
    outputs = run_session(
        cfg,
        iter_pcm=stream,
        provider=provider,
        pcm_to_wav_fn=wav_fn,
        session_tag=session_tag,
    )
    msg = str(outputs.get("answer_text") or "").strip() or "识曲完成"
    return msg, outputs


dispatch = run_from_params
