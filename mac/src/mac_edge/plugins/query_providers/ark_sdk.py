"""Shared Ark SDK client for query.content (text + images)."""

from __future__ import annotations

import logging

from mac_edge.plugins.query_providers import QueryProviderError

log = logging.getLogger("mac_edge.query.ark")


def ark_http_timeout(timeout_sec: float):
    """Read timeout separate from connect.

    Passing a bare float into Ark() sets *all* phases (including read) to that
    value. SDK default is connect=60 / read=600; a float 60 collapses read to
    60s, then max_retries=2 waits ~183s on a hung /responses call.
    """
    import httpx

    read = max(30.0, float(timeout_sec))
    return httpx.Timeout(connect=20.0, read=read, write=read, pool=20.0)


def make_ark_client(*, api_key: str, base_url: str, timeout_sec: float):
    try:
        from volcenginesdkarkruntime import Ark  # type: ignore
    except ImportError as e:
        raise QueryProviderError(
            'Ark SDK missing — run: pip install --upgrade "volcengine-python-sdk[ark]"'
        ) from e
    timeout = ark_http_timeout(timeout_sec)
    log.info(
        "ark client timeout connect=%ss read=%ss retries=0",
        timeout.connect,
        timeout.read,
    )
    try:
        return Ark(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )
    except TypeError:
        return Ark(base_url=base_url, api_key=api_key, timeout=timeout)
