"""Volcengine SAUC WebSocket STT (file/WAV path oriented for Phase 1)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from mac_edge.cloud_usage import increment
from mac_voice.audio.types import AudioUtterance
from mac_voice.stt.wav_store import SttWavStore
from mac_voice.vendor.sauc import protocol as sauc

log = logging.getLogger("mac_voice.stt.volc_sauc")


def _text_from_payload(payload_msg: Any) -> str:
    if not isinstance(payload_msg, dict):
        return ""
    result = payload_msg.get("result")
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        utts = result.get("utterances")
        if isinstance(utts, list):
            parts: list[str] = []
            for item in utts:
                if not isinstance(item, dict):
                    continue
                piece = str(item.get("text") or "").strip()
                if piece:
                    parts.append(piece)
            if parts:
                return "".join(parts)
    text = payload_msg.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


class VolcengineSaucSTT:
    def __init__(
        self,
        *,
        api_key: str,
        url: str,
        resource_id: str,
        seg_duration_ms: int = 200,
        app_key: str = "",
        access_key: str = "",
        wav_store: SttWavStore | None = None,
    ) -> None:
        if not api_key and not (app_key and access_key):
            raise ValueError("VolcengineSaucSTT requires api_key or app_key+access_key")
        self._api_key = api_key
        self._app_key = app_key
        self._access_key = access_key
        self._url = url
        self._resource_id = resource_id
        self._seg_duration_ms = seg_duration_ms
        self._timeout_sec = 10.0
        self._wav_store = wav_store or SttWavStore(
            directory=None,
            keep=False,
            max_age_hours=24.0,
            max_files=100,
            max_mb=200.0,
        )

    def _config(self) -> sauc.Config:
        return sauc.Config(
            api_key=self._api_key,
            app_key=self._app_key,
            access_key=self._access_key,
            resource_id=self._resource_id,
        )

    def _payload(self, fmt_rate: int) -> dict[str, Any]:
        return {
            "user": {"uid": "mac_voice"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": int(fmt_rate) or 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                # 口语顺滑会把重复词收成一遍（「面条面条」→「面条」），唤醒必须关。
                "enable_ddc": False,
                "show_utterances": True,
                # File clips are not live; second-pass helps 1s 面条面条.
                "enable_nonstream": True,
            },
        }

    async def transcribe(self, utterance: AudioUtterance) -> str:
        wav_path: Path | None = None
        owned = False
        try:
            wav_path, owned = self._wav_store.materialize(utterance)
            config = self._config()
            payload = self._payload(utterance.format.sample_rate)
            text = (
                await asyncio.wait_for(self._run_sauc(wav_path, config, payload), self._timeout_sec)
            ).strip()
            increment("volc.stt", True)
            return text
        except Exception:
            increment("volc.stt", False)
            raise
        finally:
            if wav_path is not None:
                self._wav_store.release(wav_path, owned=owned)

    async def _run_sauc(self, wav_path: Path, config: sauc.Config, payload: dict[str, Any]) -> str:
        best = ""
        last_payload: Any = None
        async with sauc.AsrWsClient(self._url, self._seg_duration_ms) as client:
            async for response in client.execute(str(wav_path), config, payload):
                if response.code != 0:
                    log.warning("SAUC code=%s payload=%s", response.code, response.payload_msg)
                last_payload = response.payload_msg
                text = _text_from_payload(response.payload_msg)
                if text:
                    best = text
                if response.is_last_package:
                    break
        if not best:
            log.info("SAUC empty last=%s", last_payload)
        return best
