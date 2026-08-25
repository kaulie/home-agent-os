"""search.images retrieves web photos via providers; independent of query.content."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import AssetRef
from mac_edge.plugins.image_search_providers import (
    ImageSearchHit,
    ImageSearchProviderError,
)
from mac_edge.plugins.image_search_providers.bing import BingImageSearchProvider
from mac_edge.plugins.image_search_providers.openverse import (
    OpenverseImageSearchProvider,
)
from mac_edge.plugins.search_images import (
    SearchImagesError,
    reset_cache_for_tests,
    search_from_params,
)

JPEG_MIN = b"\xff\xd8\xff" + b"\x00" * 40


class FakeProvider:
    name = "fake"

    def __init__(self, hits: list[ImageSearchHit]) -> None:
        self.hits = hits
        self.calls = 0

    def search(
        self,
        *,
        query: str,
        count: int,
        size: str = "",
        freshness: str = "",
        timeout_sec: float = 30.0,
    ) -> list[ImageSearchHit]:
        del query, count, size, freshness, timeout_sec
        self.calls += 1
        return list(self.hits)


def _asset() -> CapAsset:
    asset = MagicMock(spec=CapAsset)
    n = {"i": 0}

    def _reg(**kwargs):
        n["i"] += 1
        return AssetRef(
            asset_id=f"asset_search_{n['i']}",
            type="image",
            mime_type=kwargs.get("mime_type") or "image/jpeg",
        )

    asset.register_from_upload_url.side_effect = _reg
    return asset


def _upload_ok(image_bytes: bytes, *, filename: str, upload_dest: str) -> dict[str, str]:
    del image_bytes, upload_dest
    return {"photo_url": f"http://192.168.3.73:8080/{filename}", "saved_as": filename}


class SearchImagesCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_cache_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_query(self) -> None:
        with self.assertRaises(SearchImagesError) as ctx:
            search_from_params({}, asset=_asset(), provider=FakeProvider([]))
        self.assertIn("query", str(ctx.exception))

    def test_registers_asset_refs_not_photo_urls(self) -> None:
        hits = [
            ImageSearchHit(
                content_url="https://example.com/a.jpg",
                name="cat",
                host_page="https://example.com/page",
            )
        ]
        _msg, outputs = search_from_params(
            {"query": "猫 实拍", "count": "1"},
            asset=_asset(),
            provider=FakeProvider(hits),
            download=lambda url, timeout_sec=15.0: JPEG_MIN,
            upload=_upload_ok,
            cache_dir=self.cache,
            now=1.0,
        )
        self.assertIn("asset_refs", outputs)
        self.assertNotIn("photo_url", outputs)
        self.assertEqual(outputs["asset_refs"][0]["asset_id"], "asset_search_1")
        self.assertEqual(outputs["hit_count"], "1")

    def test_cache_skips_second_provider_call(self) -> None:
        hits = [ImageSearchHit(content_url="https://example.com/a.jpg", name="a")]
        prov = FakeProvider(hits)
        kwargs = dict(
            asset=_asset(),
            provider=prov,
            download=lambda url, timeout_sec=15.0: JPEG_MIN,
            upload=_upload_ok,
            cache_dir=self.cache,
            now=100.0,
        )
        search_from_params({"query": "故宫", "count": "1"}, **kwargs)
        search_from_params({"query": "故宫", "count": "1"}, **kwargs)
        self.assertEqual(prov.calls, 1)

    def test_does_not_import_query_content(self) -> None:
        import mac_edge.plugins.search_images as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("query_content", src)
        self.assertNotIn("query_providers", src)


class BingProviderTests(unittest.TestCase):
    def test_parses_bing_value_list(self) -> None:
        payload = {
            "value": [
                {
                    "contentUrl": "https://cdn.example/p.jpg",
                    "thumbnailUrl": "https://cdn.example/t.jpg",
                    "hostPageUrl": "https://news.example/p",
                    "name": "palace",
                    "encodingFormat": "jpeg",
                }
            ]
        }

        def http_json(url, *, headers, timeout_sec):
            del timeout_sec
            self.assertIn("Ocp-Apim-Subscription-Key", headers)
            self.assertIn("q=palace", url)
            return payload

        with patch.dict(
            "os.environ", {"MAC_EDGE_BING_SEARCH_KEY": "test-key"}, clear=False
        ):
            hits = BingImageSearchProvider(http_json=http_json).search(
                query="palace", count=2
            )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].content_url, "https://cdn.example/p.jpg")
        self.assertEqual(hits[0].host_page, "https://news.example/p")

    def test_missing_key_fails(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MAC_EDGE_BING_SEARCH_KEY": "",
                "BING_SEARCH_KEY": "",
                "AZURE_BING_SEARCH_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaises(ImageSearchProviderError) as ctx:
                BingImageSearchProvider(http_json=lambda **_k: {}).search(
                    query="cat", count=1
                )
        self.assertIn("密钥", str(ctx.exception))


class OpenverseProviderTests(unittest.TestCase):
    def test_parses_openverse_results(self) -> None:
        payload = {
            "results": [
                {
                    "url": "https://live.staticflickr.com/a.jpg",
                    "thumbnail": "https://live.staticflickr.com/t.jpg",
                    "foreign_landing_url": "https://flickr.com/p/1",
                    "title": "Duckling",
                    "license": "by",
                    "license_version": "4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "creator": "Ada",
                    "filetype": "jpg",
                }
            ]
        }

        def http_json(url, *, headers, timeout_sec):
            del timeout_sec
            self.assertIn("User-Agent", headers)
            self.assertIn("q=duckling", url)
            self.assertTrue(url.startswith("https://api.openverse.org/v1/images/"))
            return payload

        hits = OpenverseImageSearchProvider(http_json=http_json).search(
            query="duckling", count=3
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].content_url, "https://live.staticflickr.com/a.jpg")
        self.assertEqual(hits[0].host_page, "https://flickr.com/p/1")
        self.assertIn("by", hits[0].license)
        self.assertTrue(hits[0].license_url.startswith("https://creativecommons.org"))

    def test_missing_query_fails(self) -> None:
        with self.assertRaises(ImageSearchProviderError):
            OpenverseImageSearchProvider(http_json=lambda **_k: {}).search(
                query="  ", count=1
            )


if __name__ == "__main__":
    unittest.main()
