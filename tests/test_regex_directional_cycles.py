from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    FailureCode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import COMMON_PATTERN_ID, DIRECTIONAL_CYCLE_REGEX_SITES, PATTERN_SETS
from zodiac_v2.parsers.families import RegexFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates


def _site(direction: Direction) -> SiteConfig:
    return SiteConfig(
        "测试站",
        "https://example.test/topic/1.html",
        direction,
        SiteSection.EXISTING,
        "regex.test",
        "http_documents",
    )


def _bundle(text: str, *, source_id: str = "script:test", page_order: int = 0) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text,
                "https://example.test/topic/1.html",
                DocumentType.SCRIPT,
                0,
                source_id,
                page_order,
            ),
        )
    )


def test_configured_regex_site_uses_direction_to_select_annual_record_cycle() -> None:
    parser = RegexFamilyParser(
        (r"(\d{3})期[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪])",),
        directional_cycle_sites=("测试站",),
    )
    bundle = _bundle("测试站\n237期：兔\n236期：虎\n001期：鼠\n237期：猴")
    candidates = parser.parse(_site(Direction.TOP), bundle)

    top = validate_candidates(_site(Direction.TOP), bundle, candidates, 237)
    bottom = validate_candidates(_site(Direction.BOTTOM), bundle, candidates, 237)

    assert top.ok and top.candidate is not None and top.candidate.zodiac == "兔"
    assert bottom.ok and bottom.candidate is not None and bottom.candidate.zodiac == "猴"


def test_haoxue_buyan_uses_verified_directional_cycle_handling() -> None:
    assert "好学不厌" in DIRECTIONAL_CYCLE_REGEX_SITES


def test_gongche_bottom_uses_the_last_annual_record_cycle() -> None:
    site = SiteConfig(
        "宫车晏驾",
        "https://example.test/topic/1.html",
        Direction.BOTTOM,
        SiteSection.NEW,
        "regex.test",
        "http_documents",
    )
    parser = RegexFamilyParser(
        PATTERN_SETS[COMMON_PATTERN_ID],
        anchor_aliases={"宫车晏驾": "宫车晏驾"},
        directional_cycle_sites=DIRECTIONAL_CYCLE_REGEX_SITES,
    )
    bundle = _bundle(
        "宫车晏驾\n"
        "249期:绝杀一肖【牛】开:虎02准\n"
        "365期:绝杀一肖【马】开:龙38准\n"
        "001期:绝杀一肖【鸡】开:鼠01准\n"
        "248期:绝杀一肖【猴】开:猪20准\n"
        "249期:绝杀一肖【兔】开:00准"
    )

    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 249)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "兔"


def test_same_cycle_target_disagreement_remains_a_conflict() -> None:
    parser = RegexFamilyParser(
        (r"(\d{3})期[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪])",),
        directional_cycle_sites=("测试站",),
    )
    bundle = _bundle("测试站\n237期：兔\n237期：猴\n236期：虎")

    decision = validate_candidates(
        _site(Direction.TOP),
        bundle,
        parser.parse(_site(Direction.TOP), bundle),
        237,
    )

    assert decision.failure_code is FailureCode.CONFLICT


def test_pending_next_period_does_not_displace_bottom_target() -> None:
    parser = RegexFamilyParser(PATTERN_SETS[COMMON_PATTERN_ID])
    site = _site(Direction.BOTTOM)
    bundle = _bundle(
        "测试站\n238期:绝杀一肖【龙】开:虎17准\n239期:绝杀一肖【猪】开:00准"
    )

    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 238)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "龙"
    assert "record-status:incomplete" in candidates[-1].evidence


def test_different_documents_remain_a_source_conflict() -> None:
    parser = RegexFamilyParser(
        (r"(\d{3})期[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪])",),
        directional_cycle_sites=("测试站",),
    )
    first = _bundle("测试站\n237期：龙", source_id="script:first").documents[0]
    second = _bundle("测试站\n237期：马", source_id="script:second", page_order=1).documents[0]
    bundle = SourceBundle((first, second))

    decision = validate_candidates(
        _site(Direction.TOP),
        bundle,
        parser.parse(_site(Direction.TOP), bundle),
        237,
    )

    assert decision.failure_code is FailureCode.CONFLICT
    assert "来源冲突" in decision.reason


def test_zhangliao_top_uses_the_first_annual_record_cycle() -> None:
    site = SiteConfig(
        "张廖握子",
        "https://example.test/topic/1.html",
        Direction.TOP,
        SiteSection.NEW,
        "regex.d368d2f382dc",
        "http_documents",
    )
    parser = RegexFamilyParser(
        PATTERN_SETS["d368d2f382dc"],
        anchor_aliases={"张廖握子": "张廖握子"},
        directional_cycle_sites=DIRECTIONAL_CYCLE_REGEX_SITES,
    )
    bundle = _bundle(
        "张廖握子\n"
        "251期：绝杀①肖❁猪猪猪❁开00准\n"
        "250期：绝杀①肖❁马马马❁开蛇14准\n"
        "001期：绝杀①肖❁鸡鸡鸡❁开鼠01准\n"
        "365期：绝杀①肖❁龙龙龙❁开虎38准\n"
        "252期：绝杀①肖❁马马马❁开羊23准\n"
        "251期：绝杀①肖❁鼠鼠鼠❁开羊35准\n"
        "250期：绝杀①肖❁蛇蛇蛇❁开马12准"
    )

    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 251)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "猪"


def test_fei_ran_er_fan_top_uses_current_annual_cycle() -> None:
    site = SiteConfig(
        "废然而反",
        "https://example.test/topic/206891.html",
        Direction.TOP,
        SiteSection.NEW,
        "regex.86a7042b2c5a",
        "http_documents",
    )
    parser = RegexFamilyParser(
        PATTERN_SETS[COMMON_PATTERN_ID],
        anchor_aliases={"废然而反": "废然而反"},
        directional_cycle_sites=DIRECTIONAL_CYCLE_REGEX_SITES,
    )
    bundle = _bundle(
        "废然而反\n"
        "254期:绝杀一肖【狗】开:00准\n"
        "253期:绝杀一肖【蛇】开:龙38准\n"
        "001期:绝杀一肖【鼠】开:牛01准\n"
        "260期:绝杀一肖【马】开:虎17准\n"
        "259期:绝杀一肖【兔】开:鼠02准\n"
        "254期:绝杀一肖【龙】开:兔23准"
    )

    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 254)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "狗"
