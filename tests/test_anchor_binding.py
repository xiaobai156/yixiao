from __future__ import annotations

from zodiac_v2.contracts import (
    Direction,
    DocumentType,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.dedicated import PATTERN_SETS
from zodiac_v2.parsers.families import RegexFamilyParser
from zodiac_v2.validation.conflicts import validate_candidates


def _site() -> SiteConfig:
    return SiteConfig(
        "测试站",
        "https://example.invalid/anchor",
        Direction.TOP,
        SiteSection.EXISTING,
        "regex.86a7042b2c5a",
        "http_documents",
    )


def _bundle(*lines: str) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                "\n".join(lines),
                "https://example.invalid/anchor",
                DocumentType.SCRIPT,
                0,
                "script:anchor",
                0,
                "测试站",
            ),
        ),
        ("scan_complete:1",),
        scan_complete=True,
    )


def _parser() -> RegexFamilyParser:
    return RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=True)


def test_anchor_in_recommendation_line_is_rejected() -> None:
    bundle = _bundle("热门推荐：测试站 甲乙丙", "310期 绝杀一肖【牛】")

    assert _parser().parse(_site(), bundle) == ()


def test_recommendation_line_ends_anchor_block() -> None:
    bundle = _bundle(
        "测试站",
        "310期 绝杀一肖【牛】",
        "热门推荐：其他站点",
        "310期 绝杀一肖【狗】",
    )

    decision = validate_candidates(_site(), bundle, _parser().parse(_site(), bundle), 310)

    assert decision.ok and decision.candidate is not None
    assert decision.candidate.zodiac == "牛"


def test_plain_anchor_block_still_parses() -> None:
    bundle = _bundle("测试站", "310期 绝杀一肖【牛】")

    decision = validate_candidates(_site(), bundle, _parser().parse(_site(), bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_anchor_line_with_many_site_names_is_rejected() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        known_names=("测试站", "甲站", "乙站", "丙站"),
    )
    bundle = _bundle("测试站 甲站 乙站 丙站", "310期 绝杀一肖【牛】")

    assert parser.parse(_site(), bundle) == ()


def test_anchor_line_with_one_site_name_still_parses() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        known_names=("测试站", "甲站", "乙站", "丙站"),
    )
    bundle = _bundle("测试站", "310期 绝杀一肖【牛】")

    decision = validate_candidates(_site(), bundle, parser.parse(_site(), bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_alias_site_names_are_counted_in_nav_gate() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        anchor_aliases={"测试站": "测 试"},
        known_names=("测 试", "甲站", "乙站"),
    )
    bundle = _bundle("推荐位：测 试 甲站", "310期 绝杀一肖【牛】")

    assert parser.parse(_site(), bundle) == ()


def test_recommendation_line_with_period_is_not_rejected() -> None:
    bundle = _bundle("推荐阅读：测试站 310期 绝杀一肖【牛】")

    decision = validate_candidates(_site(), bundle, _parser().parse(_site(), bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_recommendation_line_with_period_does_not_cut_block() -> None:
    bundle = _bundle("测试站", "310期 绝杀一肖【牛】", "最新文章 311期 绝杀一肖【狗】")

    candidates = _parser().parse(_site(), bundle)

    assert (310, "牛") in {(item.period, item.zodiac) for item in candidates}


def test_overlapping_name_and_alias_counts_once() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        known_names=("测试站", "测试站绝杀"),
    )
    bundle = _bundle("测试站绝杀", "310期 绝杀一肖【牛】")

    candidates = parser.parse(_site(), bundle)

    assert (310, "牛") in {(item.period, item.zodiac) for item in candidates}


def test_two_site_names_under_recommendation_word_are_rejected() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        known_names=("测试站", "甲站"),
    )
    bundle = _bundle("精彩推荐：测试站 甲站", "310期 绝杀一肖【牛】")

    assert parser.parse(_site(), bundle) == ()


def test_anchor_line_with_other_site_name_as_column_label_parses() -> None:
    parser = RegexFamilyParser(
        PATTERN_SETS["86a7042b2c5a"],
        require_anchor=True,
        known_names=("测试站", "精杀一肖"),
    )
    bundle = _bundle("（测试站•精杀一肖）", "310期 绝杀一肖【牛】")

    candidates = parser.parse(_site(), bundle)

    assert (310, "牛") in {(item.period, item.zodiac) for item in candidates}


def test_nav_anchor_with_period_but_no_field_word_is_rejected() -> None:
    bundle = _bundle("热门推荐：测试站 310期", "310期 绝杀一肖【牛】")

    assert _parser().parse(_site(), bundle) == ()


def test_article_nav_anchor_with_pending_period_is_rejected() -> None:
    bundle = _bundle("相关文章：测试站 310期已更新", "310期 绝杀一肖【牛】")

    assert _parser().parse(_site(), bundle) == ()


def _candidate_bundle(text: str) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text,
                "https://example.invalid/anchor",
                DocumentType.SCRIPT,
                0,
                "script:anchor",
                0,
                "测试站",
            ),
        ),
        ("scan_complete:1",),
        scan_complete=True,
    )


def test_value_line_far_behind_text_lines_is_rejected() -> None:
    from zodiac_v2.contracts import Candidate
    from zodiac_v2.validation.evidence import validate_candidate_evidence

    text = (
        "测试站\n310期 本期资料说明文字比较长\n补充说明第二段内容也比较长\n"
        "补充说明第三段文字内容也很长\n绝杀一肖【牛】"
    )
    candidate = Candidate(
        310,
        "牛",
        "310期 本期资料说明文字比较长 补充说明第二段内容也比较长 补充说明第三段文字内容也很长 绝杀一肖【牛】",
        "script:anchor",
        1,
        ("section:测试站",),
    )

    decision = validate_candidate_evidence(candidate, _candidate_bundle(text))

    assert decision.failure_code is not None
    assert "行正文" in decision.reason


def test_table_cells_between_period_and_value_are_allowed() -> None:
    from zodiac_v2.contracts import Candidate
    from zodiac_v2.validation.evidence import validate_candidate_evidence

    text = "测试站\n310期\n5尾\n猴肖"
    candidate = Candidate(310, "猴", "310期 5尾 猴肖", "script:anchor", 1, ("section:测试站",))

    assert validate_candidate_evidence(candidate, _candidate_bundle(text)).ok


def test_declared_value_line_must_contain_zodiac() -> None:
    from zodiac_v2.contracts import Candidate
    from zodiac_v2.validation.evidence import validate_candidate_evidence

    text = "测试站\n310期\n绝杀一肖【兔】"
    candidate = Candidate(
        310,
        "牛",
        "310期 绝杀一肖【牛】",
        "script:anchor",
        1,
        ("section:测试站", "value-line:0"),
    )

    decision = validate_candidate_evidence(candidate, _candidate_bundle(text))

    assert decision.failure_code is not None
    assert "声明的值行不含生肖" in decision.reason


def test_declared_value_line_with_zodiac_passes() -> None:
    from zodiac_v2.contracts import Candidate
    from zodiac_v2.validation.evidence import validate_candidate_evidence

    text = "测试站\n310期\n绝杀一肖【牛】"
    candidate = Candidate(
        310,
        "牛",
        "310期 绝杀一肖【牛】",
        "script:anchor",
        1,
        ("section:测试站", "value-line:2"),
    )

    assert validate_candidate_evidence(candidate, _candidate_bundle(text)).ok
