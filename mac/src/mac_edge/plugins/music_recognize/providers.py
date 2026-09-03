"""Music recognition providers (pluggable audio fingerprint backends).

Provider selection is controlled by `MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER`
(none | mock | audd | acrcloud | shazam). Real backends are only built when
their key(s) are present. Every provider consumes a WAV blob and returns a
`SongMatch | None` (None = no match). Network/service problems raise
`ProviderError` with a user-readable message.

- mock      — deterministic fake for end-to-end testing without any key.
- audd      — https://api.audd.io (needs MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN).
- acrcloud  — standard v2 /v1/identify with HMAC-SHA1 signature.
- shazam    — reserved slot; fill in once a RapidAPI contract is chosen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable

from mac_edge.plugins.music_recognize.config import (
    PROVIDER_ACRCLOUD,
    PROVIDER_AUDD,
    PROVIDER_MOCK,
    PROVIDER_SHAZAM,
    MusicRecognizeConfig,
)

log = logging.getLogger("mac_edge.music_recognize.providers")

AUDD_ENDPOINT = "https://api.audd.io/"


class ProviderError(Exception):
    """Provider-level failure with a user-readable message."""


class ProviderNotConfiguredError(ProviderError):
    """No usable provider/key configured — capability should not be invoked."""


@dataclass(frozen=True)
class SongMatch:
    title: str
    artist: str
    album: str = ""
    confidence: float | None = None


Recognizer = Callable[[bytes], SongMatch | None]


def _import_httpx():
    try:
        import httpx
    except ImportError as e:  # pragma: no cover - env contract
        raise ProviderError("识别服务需要 httpx（pip install httpx）") from e
    return httpx


# --------------------------------------------------------------------------- mock


def recognize_mock(wav_bytes: bytes) -> SongMatch | None:
    """Deterministic fake used for end-to-end testing (no network)."""
    _ = wav_bytes
    log.info("mock music.recognize hit → 测试歌曲 / 测试歌手")
    return SongMatch(title="测试歌曲", artist="测试歌手", album="测试专辑", confidence=1.0)


# --------------------------------------------------------------------------- audd


def recognize_audd(
    wav_bytes: bytes,
    *,
    token: str,
    timeout_sec: float,
) -> SongMatch | None:
    if not wav_bytes:
        raise ProviderError("录音为空，无法识曲")
    httpx = _import_httpx()
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(
                AUDD_ENDPOINT,
                data={"api_token": token, "return": "timecode"},
                files={"file": ("sample.wav", wav_bytes, "audio/wav")},
            )
        if resp.status_code >= 400:
            raise ProviderError(f"audd 识别失败 http={resp.status_code}")
        body = resp.json()
    except ProviderError:
        raise
    except Exception as e:  # network / json
        raise ProviderError(f"audd 识别请求失败：{type(e).__name__}: {e}") from e

    if str(body.get("status") or "") != "success":
        raise ProviderError(f"audd 返回异常：{body.get('error') or body.get('status')}")
    result = body.get("result")
    if not isinstance(result, dict):
        return None
    title = str(result.get("title") or "").strip()
    artist = str(result.get("artist") or "").strip()
    if not title:
        return None
    return SongMatch(
        title=title,
        artist=artist,
        album=str(result.get("album") or "").strip(),
        confidence=None,
    )


# ------------------------------------------------------------------------ acrcloud


def acr_signature(access_key: str, access_secret: str, timestamp: str) -> str:
    """ACRCloud v2 identify request signature (HMAC-SHA1, base64)."""
    message = (
        f"POST\n/v1/identify\n{access_key}\n"
        f"data_type=audio\n{timestamp}\nsig_version=1"
    )
    digest = hmac.new(
        access_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def recognize_acrcloud(
    wav_bytes: bytes,
    *,
    access_key: str,
    access_secret: str,
    host: str,
    timeout_sec: float,
) -> SongMatch | None:
    if not wav_bytes:
        raise ProviderError("录音为空，无法识曲")
    httpx = _import_httpx()
    ts = str(int(time.time()))
    signature = acr_signature(access_key, access_secret, ts)
    endpoint = f"https://{host.rstrip('/')}/v1/identify"
    data = {
        "access_key": access_key,
        "data_type": "audio",
        "signature": signature,
        "sample_bytes": str(len(wav_bytes)),
        "timestamp": ts,
        "sig_version": "1",
    }
    files = {"sample": ("sample.wav", wav_bytes, "audio/wav")}
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(endpoint, data=data, files=files)
        if resp.status_code >= 400:
            raise ProviderError(f"ACRCloud 识别失败 http={resp.status_code}")
        body = resp.json()
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"ACRCloud 识别请求失败：{type(e).__name__}: {e}") from e

    status = body.get("status") if isinstance(body, dict) else None
    if not isinstance(status, dict) or int(status.get("code") or -1) != 0:
        msg = str((status or {}).get("msg") or body) or "ACRCloud 返回异常"
        raise ProviderError(f"ACRCloud 识别失败：{msg}")
    metadata = body.get("metadata") or {}
    music = metadata.get("music") if isinstance(metadata, dict) else None
    if not isinstance(music, list) or not music:
        return None
    first = music[0]
    title = str(first.get("title") or "").strip()
    artists = first.get("artists") or []
    artist_names = [
        str(a.get("name") or "").strip()
        for a in artists
        if isinstance(a, dict) and str(a.get("name") or "").strip()
    ]
    album = (first.get("album") or {}).get("name") if isinstance(first.get("album"), dict) else ""
    score = first.get("score")
    try:
        confidence = float(score) if score is not None else None
    except (TypeError, ValueError):
        confidence = None
    if not title:
        return None
    return SongMatch(
        title=title,
        artist=" / ".join(artist_names),
        album=str(album or "").strip(),
        confidence=confidence,
    )


# ------------------------------------------------------------------------- shazam


def recognize_shazam(
    wav_bytes: bytes,
    *,
    api_key: str,
    host: str,
    timeout_sec: float,
) -> SongMatch | None:
    """Reserved slot — complete once the chosen RapidAPI contract is known."""
    _ = (wav_bytes, api_key, host, timeout_sec)
    raise ProviderError(
        "shazam Provider 尚未接入：拿到所选 RapidAPI 契约后，在 "
        "mac_edge/plugins/music_recognize/providers.py:recognize_shazam 补全请求即可"
    )


# ------------------------------------------------------------------------ build


def build_provider(cfg: MusicRecognizeConfig) -> Recognizer:
    """Return a recognizer callable for cfg.provider, or raise readable error."""
    name = str(cfg.provider or "").strip().lower()
    if name == PROVIDER_MOCK:
        return recognize_mock
    if name == PROVIDER_AUDD:
        if not cfg.audd_token:
            raise ProviderNotConfiguredError(
                "识曲服务未配置：MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER=audd 但未设 "
                "MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN"
            )
        return partial(
            recognize_audd, token=cfg.audd_token, timeout_sec=cfg.http_timeout_sec
        )
    if name == PROVIDER_ACRCLOUD:
        missing = []
        if not cfg.acr_access_key:
            missing.append("ACR_ACCESS_KEY")
        if not cfg.acr_access_secret:
            missing.append("ACR_ACCESS_SECRET")
        if not cfg.acr_host:
            missing.append("ACR_HOST")
        if missing:
            raise ProviderNotConfiguredError(
                "识曲服务未配置：MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER=acrcloud 但缺少 "
                + "、".join(f"MAC_EDGE_MUSIC_RECOGNIZE_{key}" for key in missing)
            )
        return partial(
            recognize_acrcloud,
            access_key=cfg.acr_access_key,
            access_secret=cfg.acr_access_secret,
            host=cfg.acr_host,
            timeout_sec=cfg.http_timeout_sec,
        )
    if name == PROVIDER_SHAZAM:
        if not (cfg.shazam_key and cfg.shazam_host):
            raise ProviderNotConfiguredError(
                "识曲服务未配置：MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER=shazam 但缺少 "
                "MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_KEY / _HOST"
            )
        return partial(
            recognize_shazam,
            api_key=cfg.shazam_key,
            host=cfg.shazam_host,
            timeout_sec=cfg.http_timeout_sec,
        )
    raise ProviderNotConfiguredError(
        "识曲服务未配置：MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER=none。"
        "需要先设 Provider（mock/audd/acrcloud/shazam）及对应密钥"
    )


