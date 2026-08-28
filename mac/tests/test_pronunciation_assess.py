"""Tests for pronunciation.assess plugin: params contract, output shape,
sidecar-down failure, and advertised AssetRef fields."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from mac_edge.plugins.pronunciation_assess import (
    PronunciationAssessError,
    assess_from_params,
)


def _caps(services: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for svc in services:
        for cap in svc.get("capabilities") or []:
            out[str(cap["capability_id"])] = cap
    return out


def _fake_asset(tmp_path: str):
    """Duck-typed CapAsset stand-in (require_ref + manager + intent_id)."""
    mgr = MagicMock()
    mgr.materialize_file.side_effect = lambda ref, *, intent_id: _AudioFile(ref.asset_id, tmp_path)
    asset = MagicMock()
    asset.manager = mgr
    asset.intent_id = "intent-1"

    def require_ref(params, key="asset_ref"):
        raw = params.get(key)
        if not raw or not isinstance(raw, dict) or "asset_id" not in raw:
            raise ValueError(f"missing or invalid {key} (AssetRef required)")
        return _Ref(raw["asset_id"], raw.get("type", "audio"))

    asset.require_ref = require_ref
    return asset


class _Ref:
    def __init__(self, asset_id: str, type: str) -> None:
        self.asset_id = asset_id
        self.type = type


class _AudioFile:
    def __init__(self, asset_id: str, tmp_dir: str) -> None:
        self.path = os.path.join(tmp_dir, f"{asset_id}.wav")
        with open(self.path, "wb") as fh:
            fh.write(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    def __str__(self) -> str:
        return self.path


def _ref(asset_id: str) -> dict:
    return {"asset_id": asset_id, "type": "audio", "mime_type": "audio/wav"}


def _ok_response() -> dict:
    return {
        "overall_score": 84,
        "accuracy_score": 87,
        "fluency_score": 79,
        "completeness_score": 92,
        "prosody_score": 81,
        "duration": {"reference": 61.4, "student": 78.2},
        "problem_words": [
            {
                "word": "environment",
                "score": 58,
                "start": 31.2,
                "end": 32.8,
                "phoneme_errors": [],
                "reason": "low_confidence",
            }
        ],
        "problem_phonemes": [],
        "fluency": {
            "speech_rate": 120,
            "pause_count": 4,
            "long_pause_count": 1,
            "repetition_count": 0,
        },
        "raw_alignment": [],
        "feedback_text": "本次朗读 84 分。需要注意的词：environment。",
    }


class ParamsContractTests(unittest.TestCase):
    def test_missing_reference_audio_fails(self) -> None:
        asset = _fake_asset(self._tmp())
        with self.assertRaises(PronunciationAssessError):
            assess_from_params(
                {"student_audio": _ref("stu")}, asset=asset, timeout_sec=5.0
            )

    def test_missing_student_audio_fails(self) -> None:
        asset = _fake_asset(self._tmp())
        with self.assertRaises(PronunciationAssessError):
            assess_from_params(
                {"reference_audio": _ref("ref")}, asset=asset, timeout_sec=5.0
            )

    def test_non_cap_asset_fails(self) -> None:
        with self.assertRaises(PronunciationAssessError):
            assess_from_params(
                {"reference_audio": _ref("ref"), "student_audio": _ref("stu")},
                asset=object(),  # type: ignore[arg-type]
                timeout_sec=5.0,
            )

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="pronassess-test-")


class OutputShapeTests(unittest.TestCase):
    def test_maps_sidecar_response_to_wire_outputs(self) -> None:
        tmp = self._tmp()
        asset = _fake_asset(tmp)
        params = {"reference_audio": _ref("ref"), "student_audio": _ref("stu")}
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps(_ok_response()).encode("utf-8")
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda *a: None
        with patch("mac_edge.plugins.pronunciation_assess.urlopen", return_value=fake_resp):
            msg, outputs = assess_from_params(params, asset=asset, timeout_sec=5.0)
        for key in (
            "overall_score",
            "accuracy_score",
            "fluency_score",
            "completeness_score",
            "prosody_score",
            "duration",
            "problem_words",
            "problem_phonemes",
            "fluency",
            "raw_alignment",
            "feedback_text",
        ):
            self.assertIn(key, outputs, f"missing output key {key}")
        self.assertEqual(outputs["overall_score"], 84)
        self.assertEqual(outputs["problem_words"][0]["word"], "environment")
        self.assertEqual(outputs["feedback_text"], "本次朗读 84 分。需要注意的词：environment。")
        self.assertIn("pronunciation.assess", msg)

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="pronassess-test-")


class SidecarDownTests(unittest.TestCase):
    def test_sidecar_unreachable_fails_with_readable_msg(self) -> None:
        tmp = self._tmp()
        asset = _fake_asset(tmp)
        params = {"reference_audio": _ref("ref"), "student_audio": _ref("stu")}
        with patch(
            "mac_edge.plugins.pronunciation_assess.urlopen",
            side_effect=ConnectionRefusedError("conn refused"),
        ):
            with self.assertRaises(PronunciationAssessError) as cm:
                assess_from_params(params, asset=asset, timeout_sec=5.0)
        self.assertIn("pronunciation-service", str(cm.exception))

    def test_sidecar_error_payload_fails(self) -> None:
        tmp = self._tmp()
        asset = _fake_asset(tmp)
        params = {"reference_audio": _ref("ref"), "student_audio": _ref("stu")}
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({"error": "whisperx 未安装"}).encode("utf-8")
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda *a: None
        with patch("mac_edge.plugins.pronunciation_assess.urlopen", return_value=fake_resp):
            with self.assertRaises(PronunciationAssessError) as cm:
                assess_from_params(params, asset=asset, timeout_sec=5.0)
        self.assertIn("whisperx", str(cm.exception))

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="pronassess-test-")


class AdvertisedContractTests(unittest.TestCase):
    def _caps(self) -> dict[str, dict]:
        from mac_edge.services import default_services
        return _caps(default_services())

    def test_pronunciation_advertises_audio_asset_refs(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
        }
        # Force the sidecar-gated service to advertise by stubbing the health probe.
        with patch.dict(os.environ, env, clear=False), patch(
            "mac_edge.services._pronunciation_service_listening", return_value=True
        ):
            caps = self._caps()
        cap = caps.get("pronunciation.assess")
        self.assertIsNotNone(cap, "pronunciation.assess not advertised")
        self.assertIn("reference_audio", cap["input_schema"])
        self.assertIn("student_audio", cap["input_schema"])
        self.assertNotIn("photo_url", cap["input_schema"])
        self.assertNotIn("audio_url", cap["input_schema"])
        self.assertEqual(cap["input_schema"]["reference_audio"]["type"], "string")
        for key in ("overall_score", "feedback_text", "problem_words"):
            self.assertIn(key, cap["output_schema"])

    def test_pronunciation_not_advertised_when_sidecar_down(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "mac_edge.services._pronunciation_service_listening", return_value=False
        ):
            caps = self._caps()
        self.assertNotIn("pronunciation.assess", caps)


if __name__ == "__main__":
    unittest.main()
