"""Provider registry for query.content — independent of vision_providers."""

from __future__ import annotations

import logging
from typing import Callable

from mac_edge.plugins.query_providers import QueryProvider, QueryProviderError
from mac_edge.plugins.query_providers.ark_responses import ArkQueryProvider
from mac_edge.plugins.query_providers.config import query_provider_name
from mac_edge.plugins.query_providers.openai_chat import OpenAIChatQueryProvider

log = logging.getLogger("mac_edge.query.registry")

_FACTORY: dict[str, Callable[[], QueryProvider]] = {
    "ark": ArkQueryProvider,
    "volc": ArkQueryProvider,
    "doubao": ArkQueryProvider,
    "openai": OpenAIChatQueryProvider,
    "openai_chat": OpenAIChatQueryProvider,
}


def register_provider(name: str, factory: Callable[[], QueryProvider]) -> None:
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("provider name required")
    _FACTORY[key] = factory


def available_providers() -> list[str]:
    return sorted(set(_FACTORY))


def get_provider(name: str | None = None) -> QueryProvider:
    key = (name or query_provider_name()).strip().lower() or "ark"
    factory = _FACTORY.get(key)
    if factory is None:
        known = ", ".join(available_providers())
        raise QueryProviderError(
            f"unknown MAC_EDGE_QUERY_PROVIDER={key!r}; known: {known}"
        )
    provider = factory()
    log.info("query provider=%s", getattr(provider, "name", key))
    return provider
