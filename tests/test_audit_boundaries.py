from __future__ import annotations

import json

import pytest

from zodiac_v2.cache import validate_cache_data
from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    RunMode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.services.scrape import ScrapeService
from zodiac_v2.source.browser import BrowserCapture, BrowserResponse, browser_documents
from zodiac_v2.source.documents import discover_content_documents
from zodiac_v2.source.http import SourceFetchCode, SourceFetchError
from zodiac_v2.validation.conflicts import validate_candidates
from zodiac_v2.validation.evidence import _dynamic_record_matches


def _site() -> SiteConfig:
    return SiteConfig(
        "边界测试站",
        "https://example.test/topic/123.html",
        Direction.TOP,
        SiteSection.NEW,
        "test",
        "http_documents",
    )


def _document() -> SourceDocument:
    return SourceDocument(
        "栏目：杀肖\n236期：鼠",
        "https://example.test/topic/123.html",
        DocumentType.HTML,
        0,
        "html:test",
        0,
        "123",
    )


def _candidate() -> Candidate:
    return Candidate(
        236,
        "鼠",
        "236期：鼠",
        "html:test",
        1,
        ("section:杀肖", "anchor-line:0", "block-range:0-2"),
        record_id="123",
    )


def test_incomplete_source_scan_cannot_validate_success() -> None:
    bundle = SourceBundle(
        (_document(),),
        ("content_truncated:document_limit",),
        scan_complete=False,
    )

    decision = validate_candidates(_site(), bundle, (_candidate(),), 236)

    assert decision.failure_code is FailureCode.BOUNDARY
    assert "来源扫描未完成" in decision.reason


def test_http_documents_finishes_embedded_scan_before_accepting_candidate() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def http(self, site: SiteConfig, timeout: float) -> SourceBundle:
            self.calls.append("http")
            return SourceBundle((_document(),), ("scan_complete:0",), scan_complete=False)

        def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
            self.calls.append("embedded")
            return SourceBundle(bundle.documents, ("scan_complete:1",), scan_complete=True)

    class Parser:
        def parse(self, site: SiteConfig, bundle: SourceBundle):
            return (_candidate(),)

    gateway = Gateway()
    result = ScrapeService(gateway, Parser()).scrape_site(_site(), 236, RunMode.READ_ONLY)

    assert result.ok
    assert gateway.calls == ["http", "embedded"]


def test_truncated_embedded_scan_cannot_be_accepted() -> None:
    class Gateway:
        def http(self, site: SiteConfig, timeout: float) -> SourceBundle:
            return SourceBundle((_document(),), ("scan_complete:0",), scan_complete=False)

        def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
            return SourceBundle(
                bundle.documents,
                ("content_truncated:depth_limit",),
                scan_complete=False,
            )

    class Parser:
        def parse(self, site: SiteConfig, bundle: SourceBundle):
            return (_candidate(),)

    result = ScrapeService(Gateway(), Parser()).scrape_site(_site(), 236)

    assert not result.ok
    assert result.failure_code is FailureCode.BOUNDARY
    assert "来源扫描未完成" in result.reason


def test_content_discovery_rejects_cross_origin_whitelisted_paths() -> None:
    html = (
        '<script src="https://evil.test/upload/script/history.js"></script>'
        '<iframe src="https://evil.test/main/bbs/history.html"></iframe>'
    )

    assert discover_content_documents(html, "https://example.test/topic/123.html") == ()


def test_content_discovery_accepts_only_explicit_allowed_origin() -> None:
    html = (
        '<script src="https://xia01.cosds.ahsccn.com/upload/script/08/content.js"></script>'
        '<script src="https://evil.test/upload/script/history.js"></script>'
    )

    resources = discover_content_documents(
        html,
        "https://example.test/topic/123.html",
        allowed_origins={"https://xia01.cosds.ahsccn.com"},
    )

    assert [resource.url for resource in resources] == [
        "https://xia01.cosds.ahsccn.com/upload/script/08/content.js"
    ]


def test_content_discovery_accepts_current_cdn_origin() -> None:
    html = '<script src="https://xia01.cosds.aohjifv.com/upload/script/08/content.js"></script>'

    resources = discover_content_documents(
        html,
        "https://example.test/topic/123.html",
        allowed_origins={"https://xia01.cosds.aohjifv.com"},
    )

    assert [resource.url for resource in resources] == [
        "https://xia01.cosds.aohjifv.com/upload/script/08/content.js"
    ]


def test_content_discovery_does_not_treat_upload_image_as_script() -> None:
    html = '<img src="/upload/2023-07-29/photo.jpg">'

    assert discover_content_documents(html, "https://example.test/topic/123.html") == ()


class _Renderer:
    def __init__(self, capture: BrowserCapture) -> None:
        self.capture_value = capture

    def capture(self, url: str, *, timeout: float, allowed_response_urls=(), allowed_response_origins=()):
        return self.capture_value


def test_browser_page_limit_is_measured_in_utf8_bytes() -> None:
    renderer = _Renderer(BrowserCapture("https://example.test/page", "汉汉", ()))

    with pytest.raises(SourceFetchError) as caught:
        browser_documents(renderer, "https://example.test/page", max_chars=5)

    assert caught.value.code is SourceFetchCode.TOO_LARGE
    assert "字节" in str(caught.value)


def test_browser_json_response_is_bounded_before_acceptance() -> None:
    response_url = "https://example.test/api/data"
    renderer = _Renderer(
        BrowserCapture(
            "https://example.test/page",
            "ok",
            (BrowserResponse(response_url, 200, "application/json", '{"value":"汉"}'),),
        )
    )

    with pytest.raises(SourceFetchError) as caught:
        browser_documents(
            renderer,
            "https://example.test/page",
            max_chars=8,
            allowed_response_urls=(response_url,),
        )

    assert caught.value.code is SourceFetchCode.TOO_LARGE


def _cache_site(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "缓存站",
        "url": "https://example.test/topic/123.html",
        "pick": "top",
        "section": "已有站点",
        "records": [{"period": 236, "zodiac": "鼠"}],
        "fingerprint": "鼠",
        "record_provenance": {
            "236": {
                "validation_status": "validated",
                "source_id": "html:test",
                "source_url": "https://example.test/topic/123.html",
                "evidence_sha256": "a" * 64,
            }
        },
    }
    value.update(overrides)
    return value


def _cache_root(site: dict[str, object], *, latest_period: int = 236) -> dict[str, object]:
    return {
        "window_back_periods": 10,
        "latest_period": latest_period,
        "sites": [site],
        "quarantined_sites": [],
    }


@pytest.mark.parametrize(
    ("site", "message"),
    [
        (_cache_site(section="错误分区"), "缓存目录分类非法"),
        (_cache_site(pick="left"), "缓存方向非法"),
    ],
)
def test_cache_rejects_invalid_formal_identity(site: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_cache_data(_cache_root(site))


def test_cache_rejects_latest_period_outside_contract() -> None:
    with pytest.raises(ValueError, match="latest_period"):
        validate_cache_data(_cache_root(_cache_site(), latest_period=10_000))


def test_cache_rejects_records_newer_than_latest_period() -> None:
    with pytest.raises(ValueError, match="晚于 latest_period"):
        validate_cache_data(_cache_root(_cache_site(), latest_period=235))


def test_cache_rejects_malformed_provenance_hash() -> None:
    site = _cache_site(
        record_provenance={
            "236": {
                "validation_status": "validated",
                "source_id": "html:test",
                "source_url": "https://example.test/topic/123.html",
                "evidence_sha256": "not-a-sha256",
            }
        }
    )

    with pytest.raises(ValueError, match="evidence_sha256"):
        validate_cache_data(_cache_root(site))


def test_cache_rejects_record_without_matching_provenance() -> None:
    with pytest.raises(ValueError, match="必须与 records 完整对应"):
        validate_cache_data(_cache_root(_cache_site(record_provenance={})))


def test_dynamic_topic_period_evidence_must_equal_candidate_period() -> None:
    body = json.dumps(
        [{"id": 7, "topic": "236", "content": "236期杀鼠"}],
        ensure_ascii=False,
    )
    candidate = Candidate(
        236,
        "鼠",
        "236期杀鼠",
        "api:test",
        0,
        ("heading:forum-draw:236", "topic-period:235"),
        record_id="7",
    )

    assert not _dynamic_record_matches(body, candidate)
