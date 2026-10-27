from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from zodiac_v2.contracts import CacheRecord, Direction, SiteSection

CacheIdentity = tuple[str, str, Direction, SiteSection]

# 重复判定门槛：双方各自必须凑满 10 条记录，且共同期逐期全等。
# 缺期不影响判定（缓存窗口内缺某期是抓取缺口，不是「数据不同」）。
DUPLICATE_WINDOW = 10
# 兼容旧调用方的名称
MINIMUM_IDENTICAL_PERIODS = DUPLICATE_WINDOW


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    name: str
    url: str
    direction: Direction
    section: SiteSection
    common_periods: tuple[int, ...]
    identical_periods: tuple[int, ...] = ()
    basis: str = "window"
    longest_run: tuple[int, ...] = ()

    @property
    def identity(self) -> CacheIdentity:
        return (self.name, self.url, self.direction, self.section)

    @property
    def identical_on_all_common(self) -> bool:
        """共同期是否逐期全等。"""
        return (
            bool(self.common_periods)
            and tuple(sorted(self.common_periods, reverse=True))
            == tuple(sorted(self.identical_periods, reverse=True))
        )

    @property
    def run_length(self) -> int:
        return len(self.longest_run)

    @property
    def risk(self) -> str:
        """只有「满 10 期且逐期全等」才算 confirmed，其余一律 suspected。

        规则（用户 2026-10-22 确认）：没达到 10 期不算重复。
        因此 confirmed 需要同时满足：
          1. 双方各自记录数都达到 10（由调用方写入 basis / counts 保证）；
          2. 共同期逐期全等。
        """
        if self.basis == "window" and self.identical_on_all_common:
            return "confirmed"
        return "suspected"


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
    window: int = DUPLICATE_WINDOW,
) -> tuple[DuplicateMatch, ...]:
    """Compare one candidate sequence with explicitly supplied recent-cache records.

    判定规则（用户确认）：**没达到 10 期不算重复**。

    * confirmed：双方各自记录数都 >= window，且共同期逐期全等；
    * suspected：其余所有命中（供人工确认，不阻断写入）。
    """
    if isinstance(minimum_consecutive_periods, bool) or minimum_consecutive_periods <= 0:
        raise ValueError("判重所需连续期数必须是正整数")
    if isinstance(window, bool) or window <= 0:
        raise ValueError("判重窗口必须是正整数")
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
        if not common_periods:
            continue
        identical = tuple(period for period in common_periods if candidate[period] == baseline[period])

        # 连续段（仅作参考信息，不再作为判定依据）
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
        longest = max(runs, key=lambda run: (len(run), run[0] if run else 0)) if runs else ()

        full_window = (
            len(candidate) >= window
            and len(baseline) >= window
            and len(identical) == len(common_periods)
        )
        basis = "window" if full_window else "partial"
        if not full_window and len(longest) < minimum_consecutive_periods:
            continue
        matches.append(
            DuplicateMatch(*identity, common_periods, identical, basis, longest)
        )
    return tuple(matches)


def blocking_matches(matches: Iterable[DuplicateMatch]) -> tuple[DuplicateMatch, ...]:
    """返回必须阻断写入的命中（confirmed）。

    只报告不阻断是历史缺陷的根因，写入链路必须调用本函数并据此失败。
    """
    return tuple(match for match in matches if match.risk == "confirmed")
