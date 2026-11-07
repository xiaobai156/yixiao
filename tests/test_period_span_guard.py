from __future__ import annotations

from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    SiteConfig,
    SiteSection,
    SourceBundle,
    SourceDocument,
)
from zodiac_v2.parsers.common import TextLine
from zodiac_v2.parsers.dedicated import PATTERN_SETS
from zodiac_v2.parsers.families import RegexFamilyParser, _line_windows
from zodiac_v2.validation.conflicts import validate_candidates
from zodiac_v2.validation.evidence import validate_candidate_evidence


def _site() -> SiteConfig:
    return SiteConfig(
        "测试站",
        "https://example.invalid/period-span",
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
                "https://example.invalid/period-span",
                DocumentType.SCRIPT,
                0,
                "script:period-span",
                0,
                "测试站",
            ),
        ),
        ("scan_complete:1",),
        scan_complete=True,
    )


def test_line_windows_stop_before_next_period_line() -> None:
    lines = (
        TextLine("310期资料更新中"),
        TextLine("309期 绝杀一肖【牛】开:狗"),
        TextLine("其他内容"),
    )

    assert _line_windows(lines, 0) == ("310期资料更新中",)


def test_line_windows_still_join_value_on_following_line() -> None:
    lines = (
        TextLine("310期"),
        TextLine("绝杀一肖【牛】"),
    )

    assert _line_windows(lines, 0) == ("310期", "310期 绝杀一肖【牛】")


def test_line_windows_keep_value_line_with_previous_draw_note() -> None:
    lines = (
        TextLine("310期 资料"),
        TextLine("绝杀一肖【牛】(309期开:狗)"),
    )

    assert _line_windows(lines, 0) == ("310期 资料", "310期 资料 绝杀一肖【牛】(309期开:狗)")


def test_regex_family_parses_value_line_with_previous_draw_note() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站", "310期 资料", "绝杀一肖【牛】(309期开:狗)")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (310, "牛")


def test_regex_family_cannot_borrow_previous_issue_value() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("310期资料更新中", "309期 绝杀一肖【牛】开:狗")

    candidates = parser.parse(site, bundle)
    decision = validate_candidates(site, bundle, candidates, 310)

    assert not decision.ok
    assert (310, "牛") not in {(item.period, item.zodiac) for item in candidates}


def test_regex_family_still_parses_single_line_record() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站", "310期 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (310, "牛")


def test_evidence_ignores_ordinal_issue_label() -> None:
    text = "测试站 310期 本月第2期 绝杀一肖【牛】"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "牛", text, "script:period-span", 0, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    assert validate_candidate_evidence(candidate, bundle).ok


def test_evidence_rejects_foreign_period_before_zodiac() -> None:
    text = "310期资料更新中 309期 绝杀一肖【牛】"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "牛", text, "script:period-span", 0, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    decision = validate_candidate_evidence(candidate, bundle)

    assert decision.failure_code is FailureCode.FIELD
    assert "其他期数" in decision.reason


def test_evidence_rejects_bare_di_prefix_of_other_issue() -> None:
    text = "测试站 310期 第309期 绝杀一肖【牛】"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "牛", text, "script:period-span", 0, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    decision = validate_candidate_evidence(candidate, bundle)

    assert decision.failure_code is FailureCode.FIELD


def test_evidence_rejects_di_prefixed_target_issue_with_other_issue() -> None:
    text = "测试站 第310期 第309期 绝杀一肖【牛】"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "牛", text, "script:period-span", 0, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    assert validate_candidate_evidence(candidate, bundle).failure_code is FailureCode.FIELD


def test_decorated_next_record_stops_join() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站", "310期 测试站", "▶第309期 绝杀一肖【牛】开:狗")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_inline_span_merge_does_not_borrow() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    document = SourceDocument(
        "<p>310期 <span>第309期 绝杀一肖【牛】</span></p>",
        "https://example.invalid/period-span",
        DocumentType.HTML,
        0,
        "html:period-span",
        0,
    )
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_previous_draw_note_period_is_exempt() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 上期309期开狗 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (310, "牛")


def test_streak_note_period_is_exempt() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 连续9期精准 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_fullwidth_period_passes_own_period_check() -> None:
    text = "测试站 ３１０期 绝杀一肖【牛】"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "牛", text, "script:period-span", 0, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    assert validate_candidate_evidence(candidate, bundle).ok


def test_bare_period_prefix_without_qi_char_is_accepted() -> None:
    text = "测试站\n310杀鸡"
    document = SourceDocument(
        text,
        "https://example.invalid/period-span",
        DocumentType.SCRIPT,
        0,
        "script:period-span",
        0,
    )
    candidate = Candidate(310, "鸡", "310杀鸡", "script:period-span", 1, ("section:测试站",))
    bundle = SourceBundle((document,), ("scan_complete:1",), scan_complete=True)

    assert validate_candidate_evidence(candidate, bundle).ok


def test_previous_draw_without_marker_is_rejected() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 309期开:狗 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_marked_reference_period_is_exempt() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 上期开:狗(309期) 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_bare_period_mid_prefix_is_rejected() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 心水309杀鸡 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_bare_period_line_stops_join() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站", "310期 资料", "309杀鸡 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_marker_reference_with_field_word_is_rejected() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 参考309期杀鸡 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_bare_period_with_marker_is_exempt() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 上期309杀鸡 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_year_is_not_a_bare_period() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 2026必杀 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert decision.ok and decision.candidate is not None


def test_marker_reference_before_field_word_is_rejected() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 参考309期 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok


def test_marker_reference_with_separator_before_field_word_is_rejected() -> None:
    parser = RegexFamilyParser(PATTERN_SETS["86a7042b2c5a"], require_anchor=False)
    site = _site()
    bundle = _bundle("测试站 310期 参考309期、杀鸡 绝杀一肖【牛】")

    decision = validate_candidates(site, bundle, parser.parse(site, bundle), 310)

    assert not decision.ok
