from __future__ import annotations

import json

from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.services.scrape import (
    DefaultSourceGateway,
    ScrapeService,
    _article_api_bundle,
)
from zodiac_v2.source.api import derived_article_api_urls
from zodiac_v2.source.documents import source_identity


def _site(policy: str, url: str = "https://example.test/source") -> SiteConfig:
    return SiteConfig(
        "测试站",
        url,
        Direction.TOP,
        SiteSection.EXISTING,
        "test-parser",
        policy,
    )


def _document(text: str, *, url: str = "https://example.test/source") -> SourceDocument:
    return SourceDocument(text, url, DocumentType.HTML, 0, "test-source", 0)


def test_article_api_bundle_returns_only_a_target_bundle_or_none() -> None:
    site = _site("http_then_browser", "https://example.test/article/admin/abc123?url=x")
    complete_document = SourceDocument(
        json.dumps({"id": "abc123", "content": "目标文章正文"}),
        "https://example.test/api/proxy/admin-articles/abc123",
        DocumentType.JSON,
        0,
        "api:abc123",
        0,
    )
    empty_document = SourceDocument(
        "{}",
        "https://example.test/api/proxy/admin-articles/abc123",
        DocumentType.JSON,
        0,
        "api:abc123-empty",
        0,
    )

    complete = _article_api_bundle(site, (complete_document,))
    empty = _article_api_bundle(site, (empty_document,))

    assert complete is not None
    assert complete.documents[0].record_id == "abc123"
    assert empty is None


def test_lottery_article_uses_same_record_id_and_manager_api() -> None:
    url = "https://example.test/article/lottery/abc123?url=x"

    assert source_identity(url).article_id == "abc123"
    assert derived_article_api_urls(url) == (
        "https://example.test/api/proxy/manager-articles/abc123",
        "https://example.test/api/proxy/admin-articles/abc123",
    )

    site = _site("api_then_http", url)
    document = SourceDocument(
        json.dumps({"id": "abc123", "content": "目标文章正文"}),
        "https://example.test/api/proxy/manager-articles/abc123",
        DocumentType.JSON,
        0,
        "api:abc123",
        0,
    )
    bundle = _article_api_bundle(site, (document,))

    assert bundle is not None
    assert bundle.documents[0].record_id == "abc123"


def test_http_then_browser_fallback_requires_an_empty_http_shell() -> None:
    class Gateway:
        def __init__(self, document: SourceDocument) -> None:
            self.document = document
            self.calls: list[str] = []

        def http(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("http")
            return SourceBundle((self.document,))

        def browser(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("browser")
            return SourceBundle((_document("浏览器正文", url=site.url),))

    class EmptyParser:
        def parse(self, site: SiteConfig, bundle: SourceBundle):
            return ()

    non_empty_gateway = Gateway(_document("HTTP 200 but target is incomplete"))
    ScrapeService(non_empty_gateway, EmptyParser()).scrape_site(
        _site("http_then_browser"), 225
    )
    assert non_empty_gateway.calls == ["http"]

    empty_gateway = Gateway(_document("<html><script>shell()</script></html>"))
    ScrapeService(empty_gateway, EmptyParser()).scrape_site(_site("http_then_browser"), 225)
    assert empty_gateway.calls == ["http", "browser"]


def test_http_then_browser_completes_http_content_scan_before_validation() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def http(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("http")
            return SourceBundle(
                (_document("栏目：杀肖\n236期：鼠", url=site.url),),
                ("scan_complete:0",),
                scan_complete=False,
            )

        def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
            self.calls.append("embedded")
            return SourceBundle(bundle.documents, ("scan_complete:1",), scan_complete=True)

        def browser(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("browser")
            raise AssertionError("HTTP 内容完整时不应启动浏览器")

    class Parser:
        def parse(self, site: SiteConfig, bundle: SourceBundle):
            return (
                Candidate(
                    236,
                    "鼠",
                    "236期：鼠",
                    "test-source",
                    0,
                    ("section:杀肖", "anchor-line:0", "block-range:0-2"),
                ),
            )

    gateway = Gateway()
    result = ScrapeService(gateway, Parser()).scrape_site(
        _site("http_then_browser", "https://example.test/source"),
        236,
    )

    assert result.ok
    assert gateway.calls == ["http", "embedded"]


def test_default_gateway_has_no_independent_freshness_hook() -> None:
    gateway = DefaultSourceGateway(transport=object(), renderer=object())

    assert not hasattr(gateway, "independent_probe")


def test_fixed_browser_policy_does_not_probe_http() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def browser(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("browser")
            return SourceBundle((_document("杀肖\n236期：鼠", url=site.url),), scan_complete=True)

    class Parser:
        def parse(self, site: SiteConfig, bundle: SourceBundle):
            return (
                Candidate(
                    236,
                    "鼠",
                    "236期：鼠",
                    "test-source",
                    1,
                    ("section:杀肖", "anchor-line:0", "block-range:0-2"),
                ),
            )

    gateway = Gateway()
    result = ScrapeService(gateway, Parser()).scrape_site(_site("browser"), 236)

    assert result.ok
    assert gateway.calls == ["browser"]
