"""Planner cache fingerprint and stale empty-plan guards."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

import home_brain as hb  # noqa: E402


class PlannerCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        hb.mock_cache.clear()

    def test_cache_key_changes_with_catalog_fingerprint(self) -> None:
        self.assertNotEqual(
            hb.get_cache_key("关闭客厅空调", "voice", "aaaaaaaaaaaaaaaa"),
            hb.get_cache_key("关闭客厅空调", "voice", "bbbbbbbbbbbbbbbb"),
        )

    def test_stale_empty_plan_cache_is_rejected(self) -> None:
        catalog = [
            {
                "capability_id": "climate.set",
                "edge_id": "edge-mac",
                "display_name": "客厅空调",
                "typical_triggers": ["关闭客厅空调", "关掉空调"],
            }
        ]
        stale = json.dumps({"plan": [], "missing_capabilities": [{"capability": "ac.set"}]})
        fp = hb._capability_registry_fingerprint(catalog)
        hb.set_cache("关闭客厅空调", stale, "voice", catalog_fingerprint=fp)
        hit = hb.get_cache("关闭客厅空调", "voice", catalog_fingerprint=fp)
        self.assertIsNotNone(hit)
        self.assertTrue(
            hb._planner_empty_plan_unreliable("关闭客厅空调", hit, catalog)
        )

    def test_normalize_missing_capability_alias(self) -> None:
        catalog = [{"capability_id": "climate.set", "edge_id": "edge-mac"}]
        notes = hb._normalize_capability_notes(
            [{"capability": "ac.set", "reason": "need ac"}],
            catalog,
        )
        self.assertEqual(notes, [])

    def test_normalize_missing_capability_maps_unknown_alias(self) -> None:
        notes = hb._normalize_capability_notes(
            [{"capability": "ac.set", "reason": "offline"}],
            catalog=[],
        )
        self.assertEqual(notes[0]["capability"], "climate.set")

    def test_call_ark_rejects_stale_empty_plan_cache(self) -> None:
        catalog = [
            {
                "capability_id": "climate.set",
                "edge_id": "edge-mac",
                "display_name": "客厅空调",
                "typical_triggers": ["关闭客厅空调"],
            }
        ]
        stale = json.dumps({"plan": []})
        fp = hb._capability_registry_fingerprint(catalog)
        hb.set_cache("关闭客厅空调", stale, "voice", catalog_fingerprint=fp)
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "关闭客厅空调",
                "source": "voice",
                "status_log": [],
            }
        )
        good = json.dumps(
            {
                "goal": "关空调",
                "plan": [
                    {
                        "step": 1,
                        "capability": "climate.set",
                        "input_constrict": {"appliance": "客厅空调", "power": "off"},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                        "assigned_edge_id": "edge-mac",
                    }
                ],
                "presentation": {"type": "text", "from": "status_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
                "required_capabilities": ["climate.set"],
                "reason": "ok",
            }
        )

        def fake_urlopen(_req, timeout=180):
            body = json.dumps(
                {
                    "choices": [
                        {"message": {"content": good}},
                    ]
                }
            ).encode("utf-8")
            return unittest.mock.MagicMock(read=lambda: body)

        with patch.object(hb, "_capability_registry_for_prompt", return_value=catalog), patch(
            "urllib.request.urlopen", side_effect=fake_urlopen
        ):
            result = hb.call_ark(
                "关闭客厅空调",
                "sess",
                "u1",
                iid,
                0,
                intent=hb.get_intent(iid),
            )
        self.assertFalse(result.get("cache_hit"))
        self.assertIn("climate.set", result["ans"])


if __name__ == "__main__":
    unittest.main()
