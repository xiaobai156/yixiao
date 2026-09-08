from __future__ import annotations

import pytest

import zodiac_v2.source.http as http_module
from zodiac_v2.source.http import (
    HttpResponse,
    ResilientHttpTransport,
    SourceFetchCode,
    SourceFetchError,
)


class _Primary:
    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        raise SourceFetchError(SourceFetchCode.NETWORK, "primary failed", url=url)


class _Fallback:
    def __init__(self) -> None:
        self.timeout: float | None = None

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        self.timeout = timeout
        return HttpResponse(200, url, b"ok")


def test_http_fallback_uses_only_remaining_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    moments = iter((10.0, 12.0))
    monkeypatch.setattr(http_module, "monotonic", lambda: next(moments))
    fallback = _Fallback()

    ResilientHttpTransport(_Primary(), fallback).request(
        "https://example.test/page",
        timeout=5,
        max_bytes=100,
    )

    assert fallback.timeout == pytest.approx(3.0)
