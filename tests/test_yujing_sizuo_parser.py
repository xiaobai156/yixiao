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

_URL = "https://example.invalid/topic/800309.html"


def _site() -> SiteConfig:
    return SiteConfig(
        "语惊四座",
        _URL,
        Direction.TOP,
        SiteSection.NEW,
        "family.strict_article",
        "browser",
    )


def _bundle(*lines: str) -> SourceBundle:
    html = "<div>" + "</div><div>".join(lines) + "</div>"
    return SourceBundle(
        (SourceDocument(html, _URL, DocumentType.BROWSER, 0, "browser:yujing", 0, "800309"),),
        ("browser:200", "scan_complete:1"),
        scan_complete=True,
    )


def _page(*extra: str) -> SourceBundle:
    body = [
        "305期:49军师网【绝杀一肖】福安来料",
        "作者:语惊四座",
        "305期:绝杀一肖【狗肖】开：000准",
        "304期:绝杀一肖【蛇肖】开：狗21准",
        "002期:绝杀一肖【马肖】开：猴22准",
        "001期:绝杀一肖【猴肖】开：牛29准",
        # 上一年度的整段循环，末条是旧年 305 期，取值与当年不同
        "365期:绝杀一肖【蛇肖】开：龙26准",
        "306期:绝杀一肖【鼠肖】开：牛17准",
        "305期:绝杀一肖【猪肖】开：鼠42准",
    ]
    return _bundle(*body, *extra)


def test_current_year_305_wins_over_previous_year_305() -> None:
    site = _site()
    bundle = _page()

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 305)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (305, "狗")


def test_same_source_without_author_anchor_is_ignored() -> None:
    """标题同构但作者锚点不符时整块不采纳，避免抓到别的站/别的作者。"""
    site = _site()
    bundle = _bundle(
        "305期:49军师网【绝杀一肖】福安来料",
        "作者:别人",
        "305期:绝杀一肖【狗肖】开：000准",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)

    assert candidates == ()


def test_missing_current_year_305_fails_direction_boundary() -> None:
    site = _site()
    bundle = _bundle(
        "304期:49军师网【绝杀一肖】福安来料",
        "作者:语惊四座",
        "304期:绝杀一肖【蛇肖】开：狗21准",
        "303期:绝杀一肖【虎肖】开：虎17错",
    )

    candidates = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS).parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 305)

    assert not decision.ok
