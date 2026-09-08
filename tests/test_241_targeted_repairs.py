from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import (
    ANCHOR_ALIASES,
    KaijiangFacaiTableParser,
    PATTERN_SETS,
    STRICT_ARTICLE_SPECS,
)
from zodiac_v2.parsers.families import RegexFamilyParser, StrictArticleFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates


def _site(name: str, parser_id: str, direction: Direction = Direction.TOP) -> SiteConfig:
    return SiteConfig(
        name,
        "https://example.test/topic/1.html",
        direction,
        SiteSection.EXISTING,
        parser_id,
        "http_documents",
    )


def _bundle(text: str, document_type: DocumentType = DocumentType.HTML) -> SourceBundle:
    return SourceBundle(
        (SourceDocument(text, "https://example.test/topic/1.html", document_type, 0, "test", 0),),
        scan_complete=True,
    )


def test_mahuichuanzhen_uses_semantic_section_and_selects_241() -> None:
    site = _site("马会传真", "regex.223f1ef665ec")
    bundle = _bundle(
        "澳门马会传真『杀平专区』\n"
        "241期杀平特（3肖/2肖/1肖/1尾）\n杀一肖：猴\n"
        "240期杀平特（3肖/2肖/1肖/1尾）\n杀一肖：蛇"
    )
    parser = RegexFamilyParser(
        PATTERN_SETS["223f1ef665ec"],
        anchor_aliases=ANCHOR_ALIASES,
    )
    candidates = parser.parse(site, bundle)

    current = validate_candidates(site, bundle, candidates, 241)
    previous = validate_candidates(site, bundle, candidates, 240)
    missing = validate_candidates(site, bundle, candidates, 242)

    assert current.ok and current.candidate is not None
    assert current.candidate.zodiac == "猴"
    assert not previous.ok
    assert not missing.ok


def test_two_xiaozhuge_articles_follow_live_title_period_without_domain_anchor() -> None:
    parser = StrictArticleFamilyParser(STRICT_ARTICLE_SPECS)
    cases = (
        (
            "小诸葛一",
            "241期:澳彩小诸葛【绝杀一肖】～20843a.com\n"
            "241期：☛绝杀一肖☚【狗】开0000准\n"
            "240期：☛绝杀一肖☚【兔】开龙27准",
            "狗",
        ),
        (
            "小诸葛二",
            "241期:澳彩小诸葛【绝杀一肖】～20843a.com\n"
            "241期:【绝杀一肖】【鸡】开:0000准\n"
            "240期:【绝杀一肖】【虎】开:龙27准",
            "鸡",
        ),
    )
    for name, text, expected in cases:
        site = _site(name, "family.strict_article")
        bundle = _bundle(text, DocumentType.SCRIPT)
        candidates = parser.parse(site, bundle)
        current = validate_candidates(site, bundle, candidates, 241)
        previous = validate_candidates(site, bundle, candidates, 240)
        missing = validate_candidates(site, bundle, candidates, 242)
        assert current.ok and current.candidate is not None
        assert current.candidate.zodiac == expected
        assert not previous.ok
        assert not missing.ok


def test_kaijiang_facai_accepts_live_bare_zodiac_cell() -> None:
    url = "https://84477.kjfc88b.app:2443/welcome.html#234432"
    site = SiteConfig(
        "开奖发财",
        url,
        Direction.BOTTOM,
        SiteSection.NEW,
        "special.kaijiang_facai_table",
        "browser",
    )
    rows = (
        ("期数", "杀尾", "杀肖", "杀合", "杀波", "开奖"),
        ("240期", "2尾", "鸡", "07", "红波", "开:龙27"),
        ("241期", "1尾", "鸡", "02", "绿波", "开:赚99"),
        ("242期", "?尾", "?", "?", "?", "开:赚99"),
    )
    table = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    bundle = SourceBundle(
        (
            SourceDocument(
                f'<div class="list-title">开奖发财【综合杀料】11447.COM</div><table>{table}</table>',
                url,
                DocumentType.BROWSER,
                0,
                f"browser-page:{url}",
                0,
                "234432",
            ),
        ),
        scan_complete=True,
    )
    candidates = KaijiangFacaiTableParser().parse(site, bundle)

    current = validate_candidates(site, bundle, candidates, 241)
    previous = validate_candidates(site, bundle, candidates, 240)
    missing = validate_candidates(site, bundle, candidates, 242)

    assert current.ok and current.candidate is not None
    assert current.candidate.zodiac == "鸡"
    assert not previous.ok
    assert not missing.ok
