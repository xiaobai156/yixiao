# -*- coding: utf-8 -*-
"""判重规则：满 10 期且逐期全等才算重复（用户 2026-10-22 确认）。"""
from __future__ import annotations

from zodiac_v2.contracts import CacheRecord, Direction, SiteSection
from zodiac_v2.duplicate import (
    DUPLICATE_WINDOW,
    blocking_matches,
    find_duplicate_matches,
)

WINDOW = list(range(294, 284, -1))
SEQ = list("鸡蛇马鼠狗猪鸡兔虎龙")


def _rec(name: str, period: int, zodiac: str) -> CacheRecord:
    return CacheRecord(
        name=name,
        url=f"https://example.test/{name}",
        direction=Direction.TOP,
        section=SiteSection.EXISTING,
        period=period,
        zodiac=zodiac,
        source_id="html:test",
        source_url=f"https://example.test/{name}",
        evidence_sha256="a" * 64,
    )


def _seq(name: str, mapping: dict[int, str]) -> list[CacheRecord]:
    return [_rec(name, p, z) for p, z in mapping.items()]


def _full() -> dict[int, str]:
    return dict(zip(WINDOW, SEQ))


def test_window_is_ten() -> None:
    assert DUPLICATE_WINDOW == 10


def test_full_ten_identical_is_confirmed_and_blocking() -> None:
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", _full()))
    assert len(matches) == 1
    assert matches[0].risk == "confirmed"
    assert matches[0].basis == "window"
    assert len(blocking_matches(matches)) == 1


def test_both_sides_missing_same_period_still_confirmed() -> None:
    """双方都缺 289：各自仍是 10 条记录、共同期全等，按 B 方案仍判重复。"""
    gappy = {p: z for p, z in _full().items() if p != 289}
    # 补一条更早期，凑满 10 条（模拟真实缓存的窗口滑动）
    gappy[284] = "蛇"
    assert len(gappy) == 10
    matches = find_duplicate_matches(_seq("甲", gappy), _seq("乙", gappy))
    assert len(matches) == 1
    assert matches[0].risk == "confirmed"
    assert len(blocking_matches(matches)) == 1


def test_nine_records_only_is_not_duplicate() -> None:
    """只有 9 条记录：没达到 10 期，不算重复。"""
    nine = {p: z for p, z in _full().items() if p != 289}
    assert len(nine) == 9
    matches = find_duplicate_matches(_seq("甲", nine), _seq("乙", nine))
    assert all(match.risk == "suspected" for match in matches)
    assert blocking_matches(matches) == ()


def test_nine_identical_in_ten_is_not_duplicate() -> None:
    """10 条里只有 9 期相同：不算重复。"""
    other = dict(_full())
    other[294] = "马"
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", other))
    assert all(match.risk == "suspected" for match in matches)
    assert blocking_matches(matches) == ()


def test_eight_identical_is_not_duplicate() -> None:
    """8 期相同（此前会被判 confirmed）：新规则下不阻断。"""
    other = dict(_full())
    other[294] = "马"
    other[293] = "羊"
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", other))
    assert blocking_matches(matches) == ()


def test_suspected_still_reported() -> None:
    """疑似命中仍要返回（供打印），只是不阻断。"""
    other = dict(_full())
    other[294] = "马"
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", other))
    assert matches
    assert all(match.risk == "suspected" for match in matches)


def test_identical_on_all_common_flag() -> None:
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", _full()))
    assert matches[0].identical_on_all_common is True

    other = dict(_full())
    other[294] = "马"
    partial = find_duplicate_matches(_seq("甲", _full()), _seq("乙", other))
    assert partial
    assert partial[0].identical_on_all_common is False


def test_one_side_below_window_not_confirmed() -> None:
    """一方不足 10 条，即使共同期全等也不判重复。"""
    short = {p: z for p, z in _full().items() if p >= 290}
    assert len(short) == 5
    matches = find_duplicate_matches(_seq("甲", _full()), _seq("乙", short))
    assert blocking_matches(matches) == ()
