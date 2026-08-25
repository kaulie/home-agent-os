"""Env helpers for search.images providers. Does not read MAC_EDGE_QUERY_* / VISION_*."""

from __future__ import annotations

import os

DEFAULT_BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/images/search"
DEFAULT_OPENVERSE_ENDPOINT = "https://api.openverse.org/v1/images/"
DEFAULT_OPENVERSE_UA = "HomeAgent-search.images/0.1 (personal smart-home; +https://openverse.org)"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def image_search_provider_name() -> str:
    """Explicit env only. Empty means auto: Bing if keyed, else Openverse."""
    return (
        _env("MAC_EDGE_IMAGE_SEARCH_PROVIDER")
        or _env("MAC_EDGE_SEARCH_PROVIDER")
    ).strip().lower()


def bing_search_key() -> str:
    return (
        _env("MAC_EDGE_BING_SEARCH_KEY")
        or _env("BING_SEARCH_KEY")
        or _env("AZURE_BING_SEARCH_KEY")
    )


def bing_search_endpoint() -> str:
    return _env("MAC_EDGE_BING_SEARCH_ENDPOINT") or DEFAULT_BING_ENDPOINT


def openverse_endpoint() -> str:
    return _env("MAC_EDGE_OPENVERSE_ENDPOINT") or DEFAULT_OPENVERSE_ENDPOINT


def openverse_user_agent() -> str:
    return _env("MAC_EDGE_OPENVERSE_USER_AGENT") or DEFAULT_OPENVERSE_UA


def openverse_access_token() -> str:
    """Optional; anonymous search works. Token raises Openverse rate limits."""
    return _env("MAC_EDGE_OPENVERSE_ACCESS_TOKEN")
