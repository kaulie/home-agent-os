"""Provider registry — switch backends without changing vision.perceive wire."""

from __future__ import annotations

import logging
from typing import Callable

from mac_edge.plugins.vision_providers import VisionProvider, VisionProviderError
from mac_edge.plugins.vision_providers.ark_responses import ArkResponsesProvider
from mac_edge.plugins.vision_providers.config import vision_provider_name
from mac_edge.plugins.vision_providers.openai_chat import OpenAIChatVisionProvider

log = logging.getLogger("mac_edge.vision.registry")

_FACTORY: dict[str, Callable[[], VisionProvider]] = {
    "ark": ArkResponsesProvider,
    "volc": ArkResponsesProvider,
    "doubao": ArkResponsesProvider,
    "openai": OpenAIChatVisionProvider,
    "openai_chat": OpenAIChatVisionProvider,
}


def register_provider(name: str, factory: Callable[[], VisionProvider]) -> None:
    """Allow plugins/tests to add backends: register_provider('foo', FooProvider)."""
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("provider name required")
    _FACTORY[key] = factory


def available_providers() -> list[str]:
    return sorted(set(_FACTORY))


def get_provider(name: str | None = None) -> VisionProvider:
    key = (name or vision_provider_name()).strip().lower() or "ark"
    factory = _FACTORY.get(key)
    if factory is None:
        known = ", ".join(available_providers())
        raise VisionProviderError(
            f"unknown MAC_EDGE_VISION_PROVIDER={key!r}; known: {known}"
        )
    provider = factory()
    log.info("vision provider=%s", getattr(provider, "name", key))
    return provider
