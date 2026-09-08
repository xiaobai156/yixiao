from __future__ import annotations

import json

import pytest

from zodiac_v2.config import load_sites
from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.services.scrape import DefaultSourceGateway
from zodiac_v2.source.browser import BrowserCapture
from zodiac_v2.source.http import HttpResponse, SourceFetchError

_URL = "https://example.com/topic/272927.html"
_SCRIPT_URL = "https://example.com/upload/script/08/large.js"
_CDN_SCRIPT_URL = "https://xia01.cosds.ahsccn.com/upload/script/08/content.js"
_LARGE_BODY = b"a" * 8_000_001


class _Transport:
    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        del timeout
        assert url == _SCRIPT_URL
        if len(_LARGE_BODY) > max_bytes:
            return HttpResponse(200, url, _LARGE_BODY, (("Content-Type", "text/plain"),))
        return HttpResponse(200, url, _LARGE_BODY, (("Content-Type", "text/plain"),))


class _CdnTransport:
    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        del timeout, max_bytes
        assert url == _CDN_SCRIPT_URL
        return HttpResponse(200, url, b"237\xe6\x9c\x9f", (("Content-Type", "text/plain"),))


def _site(embedded_max_bytes: int | None = None) -> SiteConfig:
    return SiteConfig(
        "嘻嘻哈哈",
        _URL,
        Direction.BOTTOM,
        SiteSection.EXISTING,
        "family.strict_article",
        "http_documents",
        embedded_max_bytes=embedded_max_bytes,
    )


def _parent_bundle() -> SourceBundle:
    parent = SourceDocument(
        f'<script src="{_SCRIPT_URL}"></script>',
        _URL,
        DocumentType.HTML,
        0,
        f"html:{_URL}",
        0,
        "272927",
    )
    return SourceBundle((parent,), ("http:200",), scan_complete=False)


def test_embedded_source_uses_site_specific_limit() -> None:
    gateway = DefaultSourceGateway(transport=_Transport())

    bundle = gateway.embedded(_site(9_000_000), _parent_bundle(), timeout=5)

    assert len(bundle.documents) == 2
    assert len(bundle.documents[1].text) == len(_LARGE_BODY)


def test_embedded_source_keeps_default_limit_without_override() -> None:
    gateway = DefaultSourceGateway(transport=_Transport())

    with pytest.raises(SourceFetchError, match="超过 8000000"):
        gateway.embedded(_site(), _parent_bundle(), timeout=5)


def test_embedded_source_fetches_explicit_content_cdn() -> None:
    gateway = DefaultSourceGateway(transport=_CdnTransport())
    parent = SourceDocument(
        f'<script src="{_CDN_SCRIPT_URL}"></script>',
        _URL,
        DocumentType.HTML,
        0,
        f"html:{_URL}",
        0,
        "272927",
    )

    bundle = gateway.embedded(
        _site(),
        SourceBundle((parent,), ("http:200",), scan_complete=False),
        timeout=5,
    )

    assert [document.final_url for document in bundle.documents] == [_URL, _CDN_SCRIPT_URL]


def test_config_loads_embedded_limit(tmp_path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "嘻嘻哈哈",
                    "pick": "bottom",
                    "url": _URL,
                    "section": "已有站点",
                    "parser_id": "family.strict_article",
                    "source_policy": "http_documents",
                    "embedded_max_bytes": 12_000_000,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = build_registry()
    loaded = load_sites(
        path,
        parser_ids=registry.parser_ids,
        source_policies={"http_documents"},
    )

    assert loaded[0].embedded_max_bytes == 12_000_000


def test_browser_source_uses_site_specific_limit() -> None:
    class Renderer:
        def capture(self, url: str, **kwargs) -> BrowserCapture:
            del kwargs
            return BrowserCapture(url, "a" * 6_000_000, ())

    gateway = DefaultSourceGateway(transport=object(), renderer=Renderer())

    bundle = gateway.browser(_site(8_000_000), timeout=5)

    assert len(bundle.documents[0].text) == 6_000_000
