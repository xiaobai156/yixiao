from __future__ import annotations

from collections.abc import Iterable

from zodiac_v2.contracts import Candidate, Direction


def directional_candidate_window(
    candidates: Iterable[Candidate],
    direction: Direction,
) -> tuple[Candidate, ...]:
    items = tuple(sorted(candidates, key=lambda candidate: candidate.page_order))
    if direction not in {Direction.TOP, Direction.BOTTOM, Direction.LEFT}:
        raise ValueError(f"未知方向：{direction!r}")
    return items
