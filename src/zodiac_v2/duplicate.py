from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from zodiac_v2.contracts import CacheRecord, Direction, SiteSection

CacheIdentity = tuple[str, str, Direction, SiteSection]


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    name: str
    url: str
    direction: Direction
    section: SiteSection
    common_periods: tuple[int, ...]

    @property
    def identity(self) -> CacheIdentity:
        return (self.name, self.url, self.direction, self.section)

    @property
    def risk(self) -> str:
        return "confirmed" if len(self.common_periods) >= 6 else "suspected"


def _records_by_identity(records: Iterable[CacheRecord]) -> dict[CacheIdentity, dict[int, str]]:
    grouped: dict[CacheIdentity, dict[int, str]] = {}
    for record in records:
        if not isinstance(record, CacheRecord):
            raise ValueError("判重数据只能包含 CacheRecord")
        periods = grouped.setdefault(record.identity, {})
        if record.period in periods:
            raise ValueError(f"判重数据存在重复期号：{record.name} {record.period}期")
        periods[record.period] = record.zodiac
    return grouped


def find_duplicate_matches(
    candidate_records: Iterable[CacheRecord],
    baseline_records: Iterable[CacheRecord],
    *,
    minimum_consecutive_periods: int = 3,
    exclude_identity: CacheIdentity | None = None,
) -> tuple[DuplicateMatch, ...]:
    """Compare one candidate sequence with explicitly supplied recent-cache records."""
    if isinstance(minimum_consecutive_periods, bool) or minimum_consecutive_periods <= 0:
        raise ValueError("判重所需连续期数必须是正整数")
    candidate_groups = _records_by_identity(candidate_records)
    if not candidate_groups:
        raise ValueError("判重有效数据为空，不能判定为不重复")
    if len(candidate_groups) != 1:
        raise ValueError("候选判重记录必须属于同一目录身份")
    candidate_identity, candidate = next(iter(candidate_groups.items()))

    matches: list[DuplicateMatch] = []
    for identity, baseline in _records_by_identity(baseline_records).items():
        if identity == (exclude_identity or candidate_identity):
            continue
        common_periods = tuple(sorted(candidate.keys() & baseline.keys(), reverse=True))
        runs: list[tuple[int, ...]] = []
        current: list[int] = []
        previous: int | None = None
        for period in common_periods:
            if candidate[period] != baseline[period]:
                if current:
                    runs.append(tuple(current))
                current = []
                previous = None
                continue
            if current and previous is not None and period != previous - 1:
                runs.append(tuple(current))
                current = []
            current.append(period)
            previous = period
        if current:
            runs.append(tuple(current))
        qualifying = tuple(
            run for run in runs if len(run) >= minimum_consecutive_periods
        )
        if qualifying:
            longest = max(qualifying, key=lambda run: (len(run), run[0]))
            matches.append(DuplicateMatch(*identity, longest))
    return tuple(matches)
