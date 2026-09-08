from __future__ import annotations

import json

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import (
    PATTERN_SETS,
    TtssPeriodArticleParser,
    UserForumPostParser,
)
from zodiac_v2.parsers.families import RegexFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates


def test_hanwu_248_accepts_current_checkmark_format() -> None:
    api_url = "https://example.test/api/v1/users/180502/forums?per_page=20"
    site = SiteConfig(
        "寒武忌",
        "https://example.test/#/users/180502",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.user_forum_post",
        "api_then_http",
        api_url=api_url,
    )
    row = {
        "id": 15950059,
        "status": "published",
        "user_id": 180502,
        "draw": 248,
        "topic": "248 澳门风云",
        "content": "247期：杀牛√（兔40）<div>248期：杀猪√（？00）</div>",
        "user": {"id": 180502, "nickname": "寒武忌"},
    }
    document = SourceDocument(
        json.dumps([row], ensure_ascii=False),
        api_url,
        DocumentType.JSON,
        0,
        "user:180502:record:15950059",
        0,
        "15950059",
    )
    bundle = SourceBundle((document,), (), scan_complete=True)

    decision = validate_candidates(
        site,
        bundle,
        UserForumPostParser().parse(site, bundle),
        248,
    )

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猪"


def test_yizhangqingsan_uses_current_semantic_article_anchor() -> None:
    site = SiteConfig(
        "一丈青三",
        "https://example.test/pk/cmpk18.html",
        Direction.TOP,
        SiteSection.EXISTING,
        "special.ttss_period_article",
        "http_documents",
        article_keyword="立地太岁",
    )
    document = SourceDocument(
        "248期: 立地太岁 【绝杀一肖】\n【马】 开:00准",
        site.url,
        DocumentType.HTML,
        0,
        "html:cmpk18",
        0,
    )

    candidates = TtssPeriodArticleParser().parse(site, SourceBundle((document,), ()))

    assert [(item.period, item.zodiac) for item in candidates] == [(248, "马")]


def test_top_cycle_site_ignores_same_period_from_older_cycle() -> None:
    site = SiteConfig(
        "天女散花",
        "https://example.test/topic/625991.html",
        Direction.TOP,
        SiteSection.NEW,
        "regex.86a7042b2c5a",
        "http_documents",
    )
    document = SourceDocument(
        "\n".join(
            (
                "天女散花",
                "248期【绝杀一肖】【羊】开00",
                "247期【绝杀一肖】【狗】开21",
                "20期【绝杀一肖】【牛】开01",
                "249期【绝杀一肖】【兔】开02",
                "248期【绝杀一肖】【龙】开03",
            )
        ),
        site.url,
        DocumentType.SCRIPT,
        0,
        "script:annual-cycles",
        0,
    )
    bundle = SourceBundle((document,), (), scan_complete=True)
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        directional_cycle_sites={"天女散花"},
    )

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 248)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "羊"
