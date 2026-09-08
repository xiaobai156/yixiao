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
from zodiac_v2.validation.conflicts import _active_candidates, _window_conflict, validate_candidates
from zodiac_v2.validation.direction import directional_candidate_window


def _candidate(period: int, zodiac: str, position: int, *, document_id: str = "script:test") -> Candidate:
    return Candidate(
        period,
        zodiac,
        f"{period}期：{zodiac}",
        document_id,
        position,
        ("section:杀肖", "block:0", "block-range:1-6"),
    )


def _site() -> SiteConfig:
    return SiteConfig(
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.BOTTOM,
        section=SiteSection.EXISTING,
        parser_id="test",
        source_policy="http_documents",
    )


def _bundle(*lines: str) -> SourceBundle:
    return SourceBundle(
        (
            SourceDocument(
                text="\n".join(("栏目：杀肖", *lines)),
                final_url="https://example.test/topic/1.html",
                document_type=DocumentType.SCRIPT,
                priority=0,
                source_id="script:test",
                page_order=0,
            ),
        )
    )


def test_conflict_in_non_target_period_does_not_block_target() -> None:
    window = (
        _candidate(223, "马", 0),
        _candidate(223, "虎", 1),
        _candidate(224, "猴", 2),
    )

    assert _window_conflict(window, 224) is None


def test_conflict_in_target_period_still_fails() -> None:
    decision = _window_conflict(
        (_candidate(224, "猴", 0), _candidate(224, "虎", 1)),
        224,
    )

    assert decision is not None
    assert decision.failure_code is FailureCode.CONFLICT
    assert "指定 224期" in decision.reason


def test_direction_selects_one_record_cycle_inside_the_same_document() -> None:
    candidates = (
        Candidate(237, "兔", "237期：兔", "script:test", 1, ("record-cycle:0",)),
        Candidate(236, "虎", "236期：虎", "script:test", 2, ("record-cycle:0",)),
        Candidate(365, "牛", "365期：牛", "script:test", 3, ("record-cycle:1",)),
        Candidate(237, "猴", "237期：猴", "script:test", 4, ("record-cycle:1",)),
    )

    assert tuple(item.zodiac for item in _active_candidates(candidates, Direction.TOP)) == (
        "兔",
        "虎",
    )
    assert tuple(item.zodiac for item in _active_candidates(candidates, Direction.BOTTOM)) == (
        "牛",
        "猴",
    )


def test_direction_candidate_set_is_not_truncated_to_three_or_five_rows() -> None:
    candidates = tuple(_candidate(230 - index, "鼠", index) for index in range(8))

    assert directional_candidate_window(candidates, Direction.TOP) == candidates
    assert directional_candidate_window(candidates, Direction.BOTTOM) == candidates


def test_target_period_conflict_outside_old_window_is_not_hidden() -> None:
    rows = ((224, "猴"), (223, "马"), (222, "虎"), (221, "兔"), (220, "龙"), (224, "狗"))
    candidates = tuple(
        Candidate(
            period,
            zodiac,
            f"{period}期：{zodiac}",
            "script:test",
            position,
            ("section:杀肖", "block:0", "block-range:0-7"),
        )
        for position, (period, zodiac) in enumerate(rows, start=1)
    )

    decision = validate_candidates(
        SiteConfig(
            "测试站",
            "https://example.test/topic/1.html",
            Direction.TOP,
            SiteSection.EXISTING,
            "test",
            "http_documents",
        ),
        _bundle(*(candidate.raw_line for candidate in candidates)),
        candidates,
        224,
    )

    assert decision.failure_code is FailureCode.CONFLICT
    assert "猴/狗" in decision.reason


def test_direction_failure_reports_absolute_edge_without_count_window() -> None:
    rows = ((225, "鼠"), (224, "牛"), (223, "虎"), (222, "兔"))
    candidates = tuple(
        Candidate(
            period,
            zodiac,
            f"{period}期：{zodiac}",
            "script:test",
            position,
            ("section:杀肖", "block:0", "block-range:0-5"),
        )
        for position, (period, zodiac) in enumerate(rows, start=1)
    )

    decision = validate_candidates(
        SiteConfig(
            "测试站",
            "https://example.test/topic/1.html",
            Direction.TOP,
            SiteSection.EXISTING,
            "test",
            "http_documents",
        ),
        _bundle(*(candidate.raw_line for candidate in candidates)),
        candidates,
        223,
    )

    assert decision.failure_code is FailureCode.DIRECTION
    assert "首组为 225期" in decision.reason
    assert "最新3" not in decision.reason
    assert "最新5" not in decision.reason


def test_validation_ignores_223_conflict_when_target_is_224() -> None:
    candidates = (
        _candidate(220, "羊", 1),
        _candidate(221, "蛇", 2),
        _candidate(223, "马", 3),
        _candidate(223, "虎", 4),
        _candidate(224, "猴", 5),
    )

    decision = validate_candidates(_site(), _bundle(*(candidate.raw_line for candidate in candidates)), candidates, 224)

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (224, "猴")


def test_source_conflict_ignores_non_target_period() -> None:
    lines = ("220期：羊", "221期：蛇", "223期：马", "224期：猴")
    first = SourceDocument(
        text="\n".join(("栏目：杀肖", *lines)),
        final_url="https://example.test/topic/1.html",
        document_type=DocumentType.SCRIPT,
        priority=0,
        source_id="script:first",
        page_order=0,
    )
    second = SourceDocument(
        text="\n".join(("栏目：杀肖", "220期：羊", "221期：蛇", "223期：虎", "224期：猴")),
        final_url="https://example.test/topic/1.html",
        document_type=DocumentType.SCRIPT,
        priority=1,
        source_id="script:second",
        page_order=1,
    )
    evidence = ("section:杀肖", "block:0", "block-range:1-5")
    candidates = tuple(
        Candidate(period, zodiac, f"{period}期：{zodiac}", source_id, page_order, evidence)
        for source_id, offset, values in (
            ("script:first", 0, ((220, "羊"), (221, "蛇"), (223, "马"), (224, "猴"))),
            ("script:second", 1_000_000, ((220, "羊"), (221, "蛇"), (223, "虎"), (224, "猴"))),
        )
        for page_order, (period, zodiac) in enumerate(values, start=1)
        for page_order in (offset + page_order,)
    )

    decision = validate_candidates(
        _site(),
        SourceBundle((first, second)),
        candidates,
        224,
    )

    assert decision.ok
    assert decision.candidate is not None
    assert (decision.candidate.period, decision.candidate.zodiac) == (224, "猴")


def test_source_conflict_in_target_period_still_fails() -> None:
    first = SourceDocument(
        text="\n".join(("栏目：杀肖", "223期：马", "224期：猴")),
        final_url="https://example.test/topic/1.html",
        document_type=DocumentType.SCRIPT,
        priority=0,
        source_id="script:first",
        page_order=0,
    )
    second = SourceDocument(
        text="\n".join(("栏目：杀肖", "223期：虎", "224期：虎")),
        final_url="https://example.test/topic/1.html",
        document_type=DocumentType.SCRIPT,
        priority=1,
        source_id="script:second",
        page_order=1,
    )
    evidence = ("section:杀肖", "block:0", "block-range:1-3")
    candidates = (
        Candidate(223, "马", "223期：马", "script:first", 1, evidence),
        Candidate(224, "猴", "224期：猴", "script:first", 2, evidence),
        Candidate(223, "虎", "223期：虎", "script:second", 1_000_001, evidence),
        Candidate(224, "虎", "224期：虎", "script:second", 1_000_002, evidence),
    )

    decision = validate_candidates(_site(), SourceBundle((first, second)), candidates, 224)

    assert decision.failure_code is FailureCode.CONFLICT
    assert "来源冲突：指定 224期" in decision.reason


def test_direction_failure_reports_target_period_with_invalid_zodiac_field() -> None:
    site = SiteConfig(
        name="百花争春",
        url="https://example.test/article/manager/1",
        direction=Direction.BOTTOM,
        section=SiteSection.NEW,
        parser_id="test",
        source_policy="http_documents",
    )
    valid_rows = ((223, "虎"), (224, "狗"), (225, "鼠"), (226, "羊"), (227, "猴"))
    candidates = tuple(
        _candidate(period, zodiac, position)
        for position, (period, zodiac) in enumerate(valid_rows, start=1)
    )
    bundle = SourceBundle(
        (
            SourceDocument(
                text="\n".join(
                    (
                        "栏目：杀肖",
                        *(f"{period}期：{zodiac}" for period, zodiac in valid_rows),
                        "228期：【百花争春】绝杀①肖【蜀】开:0000准",
                    )
                ),
                final_url="https://example.test/article/manager/1",
                document_type=DocumentType.HTML,
                priority=0,
                source_id="script:test",
                page_order=0,
            ),
        )
    )

    decision = validate_candidates(site, bundle, candidates, 228)

    assert decision.failure_code is FailureCode.FIELD
    assert "已找到指定 228期" in decision.reason
    assert "蜀" in decision.reason
    assert "合法生肖" in decision.reason
    assert "页面候选中未找到228期" not in decision.reason
