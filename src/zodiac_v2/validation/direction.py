from __future__ import annotations

from collections.abc import Iterable

from zodiac_v2.contracts import Candidate, Direction

DEFAULT_DIRECTION_WINDOW_SIZE = 3
DIRECTION_WINDOW_SIZE = 5


def direction_window_size(candidates: Iterable[Candidate]) -> int:
    items = tuple(candidates)
    periods = [candidate.period for candidate in items]
    strict = len(items) > 30 or len(periods) != len(set(periods))
    return DIRECTION_WINDOW_SIZE if strict else DEFAULT_DIRECTION_WINDOW_SIZE


def directional_candidate_window(
    candidates: Iterable[Candidate],
    direction: Direction,
) -> tuple[Candidate, ...]:
    items = tuple(sorted(candidates, key=lambda candidate: candidate.page_order))
    if direction is Direction.LEFT:
        return items
    window_size = direction_window_size(items)
    if direction is Direction.TOP:
        return items[:window_size]
    return items[-window_size:]
