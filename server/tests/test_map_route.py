"""Tests for Amap map.route.estimate (mocked HTTP)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from map_route import (  # noqa: E402
    MapRouteError,
    estimate_route,
    geocode_place,
    normalize_mode,
    route_from_params,
)
from system_capabilities import (  # noqa: E402
    is_system_capability,
    run_system_step,
)


def _geo(lng: float, lat: float) -> bytes:
    return json.dumps(
        {"status": "1", "geocodes": [{"location": f"{lng},{lat}"}]}
    ).encode()


def _drive(distance: str = "25000", duration: str = "2100") -> bytes:
    return json.dumps(
        {
            "status": "1",
            "route": {"paths": [{"distance": distance, "duration": duration}]},
        }
    ).encode()


class NormalizeModeTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(normalize_mode("开车"), "driving")
        self.assertEqual(normalize_mode("地铁"), "transit")
        self.assertEqual(normalize_mode("步行"), "walking")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(MapRouteError):
            normalize_mode("火箭")


class GeocodeTests(unittest.TestCase):
    @patch("map_route._http_get")
    def test_geocode_ok(self, mock_get) -> None:
        mock_get.return_value = json.loads(_geo(116.4, 39.9).decode())
        lng, lat = geocode_place("望新花园", city="北京", key="test-key")
        self.assertAlmostEqual(lng, 116.4)
        self.assertAlmostEqual(lat, 39.9)


class EstimateRouteTests(unittest.TestCase):
    @patch("map_route._http_get")
    def test_driving_route(self, mock_get) -> None:
        mock_get.side_effect = [
            json.loads(_geo(116.40, 40.00).decode()),
            json.loads(_geo(116.65, 40.13).decode()),
            json.loads(_drive("32000", "2400").decode()),
        ]
        out = estimate_route(
            origin="望新花园",
            destination="顺义建邦顺颐府",
            mode="driving",
            city="北京",
            key="test-key",
        )
        self.assertIn("驾车", out["answer_text"])
        self.assertIn("望新花园", out["answer_text"])
        self.assertEqual(out["distance_km"], "32.00")
        self.assertEqual(out["duration_min"], "40")
        self.assertEqual(out["mode"], "driving")

    @patch("map_route._http_get")
    def test_transit_route(self, mock_get) -> None:
        mock_get.side_effect = [
            json.loads(_geo(116.1, 39.9).decode()),
            json.loads(_geo(116.2, 39.95).decode()),
            {
                "status": "1",
                "route": {
                    "transits": [{"distance": "18000", "duration": "3600"}]
                },
            },
        ]
        out = estimate_route(
            origin="A地",
            destination="B地",
            mode="transit",
            key="k",
        )
        self.assertEqual(out["mode"], "transit")
        self.assertIn("公共交通", out["answer_text"])

    def test_missing_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(MapRouteError):
                route_from_params({"origin": "a", "destination": "b"})


class SystemStepTests(unittest.TestCase):
    def test_is_system_capability(self) -> None:
        self.assertTrue(is_system_capability("map.route.estimate"))

    @patch("map_route._http_get")
    def test_run_system_step(self, mock_get) -> None:
        mock_get.side_effect = [
            json.loads(_geo(116.0, 40.0).decode()),
            json.loads(_geo(116.5, 40.1).decode()),
            json.loads(_drive().decode()),
        ]
        with patch.dict("os.environ", {"AMAP_WEB_KEY": "test-key"}):
            msg, out = run_system_step(
                "map.route.estimate",
                {
                    "origin": "望新花园",
                    "destination": "顺义",
                    "mode": "driving",
                },
            )
        self.assertIn("map.route.estimate", msg)
        self.assertIn("answer_text", out)
        self.assertIn("distance_km", out)


if __name__ == "__main__":
    unittest.main()
