"""Image search providers for search.images — independent of query / vision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ImageSearchProviderError(Exception):
    pass


@dataclass(frozen=True)
class ImageSearchHit:
    """One web photo hit. URLs are fetch sources, not Asset identity."""

    content_url: str
    thumbnail_url: str = ""
    host_page: str = ""
    name: str = ""
    encoding: str = ""
    license: str = ""
    license_url: str = ""

    def to_dict(self) -> dict[str, str]:
        out = {
            "content_url": self.content_url,
            "thumbnail_url": self.thumbnail_url,
            "host_page": self.host_page,
            "name": self.name,
            "encoding": self.encoding,
        }
        if self.license:
            out["license"] = self.license
        if self.license_url:
            out["license_url"] = self.license_url
        return out

    @classmethod
    def from_dict(cls, raw: object) -> "ImageSearchHit | None":
        if not isinstance(raw, dict):
            return None
        content = str(
            raw.get("content_url")
            or raw.get("contentUrl")
            or raw.get("url")
            or ""
        ).strip()
        thumb = str(
            raw.get("thumbnail_url")
            or raw.get("thumbnailUrl")
            or raw.get("thumbnail")
            or ""
        ).strip()
        if not content and not thumb:
            return None
        license_name = str(raw.get("license") or "").strip()
        version = str(raw.get("license_version") or "").strip()
        if license_name and version and version not in license_name:
            license_name = f"{license_name} {version}".strip()
        return cls(
            content_url=content,
            thumbnail_url=thumb,
            host_page=str(
                raw.get("host_page")
                or raw.get("hostPageUrl")
                or raw.get("foreign_landing_url")
                or ""
            ).strip(),
            name=str(raw.get("name") or raw.get("title") or "").strip(),
            encoding=str(
                raw.get("encoding") or raw.get("encodingFormat") or ""
            ).strip(),
            license=license_name,
            license_url=str(raw.get("license_url") or "").strip(),
        )


class ImageSearchProvider(Protocol):
    """Keyword → existing web photos. Must not download, upload, or register Assets."""

    name: str

    def search(
        self,
        *,
        query: str,
        count: int,
        size: str = "",
        freshness: str = "",
        timeout_sec: float = 30.0,
    ) -> list[ImageSearchHit]:
        ...


from mac_edge.plugins.image_search_providers.registry import (  # noqa: E402
    any_provider_configured,
    available_providers,
    get_provider,
    provider_configured,
    register_provider,
    resolve_provider_name,
)

__all__ = [
    "ImageSearchHit",
    "ImageSearchProvider",
    "ImageSearchProviderError",
    "any_provider_configured",
    "available_providers",
    "get_provider",
    "provider_configured",
    "register_provider",
    "resolve_provider_name",
]
