"""Query LLM / image providers for query.content (Edge-local, independent of vision)."""

from __future__ import annotations

from typing import Protocol


class QueryProviderError(Exception):
    pass


class QueryProvider(Protocol):
    """Text complete (+ optional image generate) → dict / bytes.

    complete() returns raw model text via raw_text / _provider_text for JSON
    parsing in query_content. Must not import vision_providers.
    """

    name: str

    def complete(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict:
        ...

    def generate_image(
        self,
        *,
        prompt: str,
        timeout_sec: float = 90.0,
    ) -> bytes:
        ...


from mac_edge.plugins.query_providers.registry import (  # noqa: E402
    available_providers,
    get_provider,
    register_provider,
)

__all__ = [
    "QueryProvider",
    "QueryProviderError",
    "available_providers",
    "get_provider",
    "register_provider",
]
