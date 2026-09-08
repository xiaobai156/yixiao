from __future__ import annotations

from pathlib import Path

from zodiac_v2.config import load_sites
from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    FailureCode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import MoranBeihuanCycleParser
from zodiac_v2.parsers.registry import build_registry
from zodiac_v2.validation.conflicts import validate_candidates

_PAGE_URL = "https://ybenrek.4vqpu-k0sfk-iazyta.xyz:16677/topic/682016.html"


def _site() -> SiteConfig:
    return SiteConfig(
        name="墨染悲欢",
        url=_PAGE_URL,
        direction=Direction.BOTTOM,
        section=SiteSection.NEW,
        parser_id="special.moran_beihuan_cycle",
        source_policy="http_documents",
    )


def _bundle(*lines: str, source_id: str = "script:detail") -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text="\n".join(lines),
                final_url=_PAGE_URL,
                document_type=DocumentType.SCRIPT,
                priority=0,
                source_id=source_id,
                page_order=0,
                record_id="682016",
            ),
        )
    )


def _two_cycle_bundle() -> SourceBundle:
    return _bundle(
        "230期〖\u200c墨染悲欢〗【绝杀一肖】",
        "\u200c墨染悲欢 发表于 05月30日 14:46:27",
        "228期:‡绝杀一肖‡【龙】开:兔15√",
        "229期:‡绝杀一肖‡【猪】开:龙02√",
        "230期:‡绝杀一肖‡【兔】开:兔39错",
        "365期:‡绝杀一肖‡【兔】开:龙26√",
        "001期:‡绝杀一肖‡【鸡】开:牛29√",
        "227期:‡绝杀一肖‡【蛇】开:兔16√",
        "228期:‡绝杀一肖‡【兔】开:猴23√",
        "229期:‡绝杀一肖‡【猪】开:蛇38√",
        "230期:‡绝杀一肖‡【鸡】开:00√",
        "上一篇：",
        "230期〖算法文心〗【绝杀一行】",
    )


def test_bottom_uses_latest_record_cycle_without_old_cycle_conflict() -> None:
    site = _site()
    bundle = _two_cycle_bundle()
    candidates = MoranBeihuanCycleParser().parse(site, bundle)

    assert [(item.period, item.zodiac) for item in candidates if item.period == 230] == [
        (230, "兔"),
        (230, "鸡"),
    ]
    assert [
        next(item for item in candidate.evidence if item.startswith("record-cycle:"))
        for candidate in candidates
        if candidate.period == 230
    ] == ["record-cycle:0", "record-cycle:1"]

    decision = validate_candidates(site, bundle, candidates, 230)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (230, "鸡")


def test_rejects_aggregate_title_without_same_block_author_and_records() -> None:
    bundle = _bundle(
        "230期〖\u200c墨染悲欢〗【绝杀一肖】",
        "230期: 牛头马面【三头中特】→横扫庄家",
        "230期〖\u200c西东字宙〗【绝杀一肖】",
        "230期: 牛头马面【三行中特】→横扫庄家",
        "230期〖\u200c像素叙事〗【绝杀一肖】",
    )

    assert MoranBeihuanCycleParser().parse(_site(), bundle) == ()


def test_requires_exact_author_and_yixiao_record_field() -> None:
    parser = MoranBeihuanCycleParser()
    assert parser.parse(
        _site(),
        _bundle(
            "230期〖墨染悲欢〗【绝杀一肖】",
            "其他作者 发表于 05月30日 14:46:27",
            "230期:‡绝杀一肖‡【鸡】开:00√",
        ),
    ) == ()
    assert parser.parse(
        _site(),
        _bundle(
            "230期〖墨染悲欢〗【绝杀一肖】",
            "墨染悲欢 发表于 05月30日 14:46:27",
            "230期:‡绝杀二尾‡【鸡】开:00√",
        ),
    ) == ()


def test_adjacent_and_missing_periods_cannot_cross_bottom_boundary() -> None:
    site = _site()
    bundle = _two_cycle_bundle()
    candidates = MoranBeihuanCycleParser().parse(site, bundle)

    adjacent = validate_candidates(site, bundle, candidates, 229)
    missing = validate_candidates(site, bundle, candidates, 231)

    assert not adjacent.ok
    assert adjacent.failure_code is FailureCode.DIRECTION
    assert "尾组为 230期" in adjacent.reason
    assert not missing.ok
    assert missing.failure_code is FailureCode.DIRECTION


def test_registry_exposes_dedicated_parser() -> None:
    assert "special.moran_beihuan_cycle" in build_registry().parser_ids


def test_formal_site_binds_dedicated_parser() -> None:
    registry = build_registry()
    sites = load_sites(
        Path("sites.json"),
        parser_ids=registry.parser_ids,
        source_policies={
            "http_documents",
            "http_consensus",
            "http_named_topic",
            "http_period_keyword_article",
            "api_then_http",
            "browser",
            "browser_user",
            "http_then_browser",
        },
    )

    site = next(item for item in sites if item.name == "墨染悲欢")

    assert site.parser_id == "special.moran_beihuan_cycle"
