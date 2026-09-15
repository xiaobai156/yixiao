from __future__ import annotations

from zodiac_v2.contracts import Direction, DocumentType, SiteConfig, SiteSection, SourceBundle, SourceDocument
from zodiac_v2.parsers.dedicated import ThinmuZhiqiuMissingParser
from zodiac_v2.validation.evidence import validate_candidate_evidence


def _site() -> SiteConfig:
    return SiteConfig(
        "薄暮知秋",
        "https://www.356161c.com/18hk/45.html",
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.thinmu_zhiqiu_missing",
        "http_documents",
    )


def test_thinmu_parser_derives_the_missing_zodiac() -> None:
    site = _site()
    html = (
        "<h3>薄暮知秋【来料11肖】</h3><div>薄暮知秋楼主</div>"
        "<div>258期:（猴鸡马蛇鼠兔牛羊虎猪龙）开鸡46中</div>"
        "<div>259期:（猪狗羊虎马鸡龙兔牛蛇猴）开？00中</div>"
    )
    document = SourceDocument(
        html,
        site.url,
        DocumentType.HTML,
        0,
        "thinmu-detail:https://www.356161c.com/18hk/45.html",
        0,
    )
    candidates = ThinmuZhiqiuMissingParser().parse(site, SourceBundle((document,)))
    assert [(candidate.period, candidate.zodiac) for candidate in candidates] == [(258, "狗"), (259, "鼠")]
    assert validate_candidate_evidence(candidates[-1], SourceBundle((document,))).ok
