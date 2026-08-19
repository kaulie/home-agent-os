"""Vision model providers for vision.perceive (Edge-local, pluggable)."""

from __future__ import annotations

from typing import Protocol


class VisionProviderError(Exception):
    pass


class VisionProvider(Protocol):
    """Analyze a public image URL + text prompt → structured dict.

    Optional `text_format` is the Ark/OpenAI responses `text=` payload
    (json_schema). Default in the Ark provider is the perception schema;
    `vision.ask` passes its own answer_text schema.

    Returns raw model text via raw_text / _provider_text for JSON parsing
    in the calling capability. Must not repair/unwrap JSON here.
    """

    name: str

    def analyze(
        self,
        *,
        image_url: str,
        prompt: str,
        timeout_sec: float = 90.0,
        text_format: dict | None = None,
    ) -> dict:
        ...


from mac_edge.plugins.vision_providers.registry import (  # noqa: E402
    available_providers,
    get_provider,
    register_provider,
)

__all__ = [
    "VisionProvider",
    "VisionProviderError",
    "available_providers",
    "get_provider",
    "register_provider",
]
