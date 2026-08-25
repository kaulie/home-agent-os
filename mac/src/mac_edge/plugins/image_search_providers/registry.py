"""Provider registry for search.images — independent of query_providers / vision_providers."""

from __future__ import annotations

import logging
from typing import Callable

from mac_edge.plugins.image_search_providers import (
    ImageSearchProvider,
    ImageSearchProviderError,
)
from mac_edge.plugins.image_search_providers.bing import BingImageSearchProvider
from mac_edge.plugins.image_search_providers.config import (
    bing_search_key,
    image_search_provider_name,
)
from mac_edge.plugins.image_search_providers.openverse import (
    OpenverseImageSearchProvider,
)

log = logging.getLogger("mac_edge.image_search.registry")

_FACTORY: dict[str, Callable[[], ImageSearchProvider]] = {
    "bing": BingImageSearchProvider,
    "azure_bing": BingImageSearchProvider,
    "azure": BingImageSearchProvider,
    "openverse": OpenverseImageSearchProvider,
    "ov": OpenverseImageSearchProvider,
}

_BING_NAMES = frozenset({"bing", "azure_bing", "azure"})
_OPENVERSE_NAMES = frozenset({"openverse", "ov"})


def register_provider(name: str, factory: Callable[[], ImageSearchProvider]) -> None:
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("provider name required")
    _FACTORY[key] = factory


def available_providers() -> list[str]:
    return sorted(set(_FACTORY))


def _canonical(name: str) -> str:
    key = (name or "").strip().lower()
    if key in _BING_NAMES:
        return "bing"
    if key in _OPENVERSE_NAMES:
        return "openverse"
    return key


def resolve_provider_name(explicit: str | None = None) -> str:
    """Step param > env > Bing if keyed > Openverse (always usable)."""
    chosen = _canonical(explicit or "") or _canonical(image_search_provider_name())
    if chosen:
        return chosen
    if bing_search_key():
        return "bing"
    return "openverse"


def provider_usable(name: str) -> bool:
    key = _canonical(name)
    if key in _OPENVERSE_NAMES or key == "openverse":
        return True
    if key in _BING_NAMES or key == "bing":
        return bool(bing_search_key())
    return False


def any_provider_configured() -> bool:
    """Openverse needs no key; Bing needs a subscription key."""
    env = _canonical(image_search_provider_name())
    if env:
        return provider_usable(env)
    return True


def provider_configured(name: str | None = None) -> bool:
    """Usable if `name` given; else True when at least one provider can run."""
    if name:
        return provider_usable(name)
    return any_provider_configured()


def get_provider(name: str | None = None) -> ImageSearchProvider:
    key = resolve_provider_name(name)
    factory = _FACTORY.get(key)
    if factory is None:
        known = ", ".join(sorted({"bing", "openverse"}))
        raise ImageSearchProviderError(
            f"unknown image search provider={key!r}; known: {known}"
        )
    if key == "bing" and not bing_search_key():
        raise ImageSearchProviderError(
            "未配置必应搜图密钥。请在 mac/.env 设置 MAC_EDGE_BING_SEARCH_KEY，"
            "或改用 Openverse（MAC_EDGE_IMAGE_SEARCH_PROVIDER=openverse）"
        )
    provider = factory()
    log.info("image search provider=%s", getattr(provider, "name", key))
    return provider
