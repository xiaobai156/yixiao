from __future__ import annotations

from zodiac_v2.contracts import CacheRecord, Direction, SiteSection
from zodiac_v2.duplicate import find_duplicate_matches


def _record(name: str, period: int, zodiac: str) -> CacheRecord:
    url = f"https://{name}.test/site"
    return CacheRecord(
        name,
        url,
        Direction.TOP,
        SiteSection.EXISTING,
        period,
        zodiac,
        f"html:{url}",
        url,
        "a" * 64,
    )


def test_default_duplicate_check_does_not_cross_numeric_period_gaps() -> None:
    candidate = [_record("候选", 225, "鼠"), _record("候选", 223, "虎"), _record("候选", 222, "兔")]
    baseline = [_record("已有", 225, "鼠"), _record("已有", 223, "虎"), _record("已有", 222, "兔")]

    assert find_duplicate_matches(candidate, baseline) == ()


def test_duplicate_check_cannot_disable_numeric_gap_boundary() -> None:
    candidate = [_record("候选", 225, "鼠"), _record("候选", 223, "虎"), _record("候选", 222, "兔")]
    baseline = [_record("已有", 225, "鼠"), _record("已有", 223, "虎"), _record("已有", 222, "兔")]

    assert find_duplicate_matches(candidate, baseline) == ()
