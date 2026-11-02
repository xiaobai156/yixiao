from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import STRICT_ARTICLE_SPECS
from zodiac_v2.parsers.families import StrictArticleFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates

_URL = "https://example.invalid/topic/504953.html"


def _site() -> SiteConfig:
    return SiteConfig(
        "爆竹声中",
        _URL,
        Direction.TOP,
        SiteSection.EXISTING,
        "family.strict_article",
        "browser",
    )


def _bundle(*lines: str) -> SourceBundle:
    html = "<div>" + "</div><div>".join(lines) + "</div>"
    return SourceBundle(
        (SourceDocument(html, _URL, DocumentType.BROWSER, 0, "browser:baozhu", 0, "504953"),),
        ("browser:200", "scan_complete:1"),
        scan_complete=True,
    )


def _article(*extra: str) -> SourceBundle:
    return _bundle(
        "306期:爆竹声中【绝杀一肖】资料已公开",
        "306期：绝杀一肖【猪猪猪】开0000准",
        "305期：绝杀一肖【兔兔兔】开蛇26准",
        "304期：绝杀一肖【虎虎虎】开狗21准",
        *extra,
    )


def test_sidebar_latest_post_list_does_not_create_competing_candidate() -> None:
    """页面下半部「最新帖」偶发出现，含别站「绝杀一头…鸡」，不得变成 306 期第二候选。"""
    site = _site()
    bundle = _article(
        "306期:人尽皆知【稳杀一波】资料已公开 306期:专横跋扈【绝杀一头】资料已公开 306期:鸡",
        "305期:人尽皆知【稳杀一波】资料已公开",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 306)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (306, "猪")


def test_article_records_keep_only_target_period_boundary() -> None:
    site = _site()
    bundle = _article()

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)

    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [
        (306, "猪"),
        (305, "兔"),
        (304, "虎"),
    ]


def test_missing_title_block_fails_closed() -> None:
    site = _site()
    bundle = _bundle(
        "306期:别站【绝杀一肖】资料已公开",
        "306期：绝杀一肖【猪猪猪】开0000准",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)

    assert candidates == ()
