from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from zodiac_v2.contracts import Candidate, SiteConfig, SourceBundle
from zodiac_v2.parsers.common import (
    TextLine,
    document_lines,
    normalize_space,
    scoped_blocks,
)

_PENDING_DRAW_PATTERN = re.compile(r"[开開]\s*[:：]?\s*0{2,4}\s*(?:准|错)?")


@dataclass(frozen=True, slots=True)
class StrictArticleSpec:
    title_pattern: str
    record_pattern: str
    author_pattern: str | None = None
    allow_pending_title: bool = False
    directional_cycles: bool = False


@dataclass(frozen=True, slots=True)
class AnchoredSectionSpec:
    anchor_pattern: str
    record_pattern: str
    stop_pattern: str | None = None
    include_anchor_line: bool = False
    record_window_lines: int = 1


@dataclass(frozen=True, slots=True)
class _CompiledStrictArticleSpec:
    title_pattern: re.Pattern[str]
    record_pattern: re.Pattern[str]
    author_pattern: re.Pattern[str] | None
    allow_pending_title: bool
    directional_cycles: bool


@dataclass(frozen=True, slots=True)
class _CompiledAnchoredSectionSpec:
    anchor_pattern: re.Pattern[str]
    record_pattern: re.Pattern[str]
    stop_pattern: re.Pattern[str] | None
    include_anchor_line: bool
    record_window_lines: int


def _physical_match_key(
    document_id: str,
    line_index: int,
    match_offset: int,
    period: int,
    zodiac: str,
) -> tuple[str, int, int, int, str]:
    """Identify one physical record without collapsing equal records elsewhere."""

    return document_id, line_index, match_offset, period, zodiac


def _window_match_location(
    lines: tuple[TextLine, ...],
    start_index: int,
    match_start: int,
) -> tuple[int, int]:
    """Map a normalized rolling-window offset back to its source line and offset."""

    cursor = 0
    for offset, line in enumerate(lines[start_index : start_index + 3]):
        line_end = cursor + len(line.text)
        if match_start <= line_end:
            return start_index + offset, max(0, match_start - cursor)
        cursor = line_end + 1
    return start_index, match_start


class RegexFamilyParser:
    def __init__(
        self,
        patterns: tuple[str, ...],
        *,
        anchor_aliases: Mapping[str, str] | None = None,
        require_anchor: bool = True,
        period_marker_required: bool = True,
        directional_cycle_sites: Collection[str] = (),
    ) -> None:
        self.patterns = tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
        self.anchor_aliases = MappingProxyType(dict(anchor_aliases or {}))
        self.require_anchor = require_anchor
        self.period_marker_required = period_marker_required
        self.directional_cycle_sites = frozenset(directional_cycle_sites)

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        anchor = self.anchor_aliases.get(site.name, site.name)
        candidates: list[Candidate] = []
        seen: set[tuple[str, int, int, int, str]] = set()
        for document in bundle.documents:
            lines = document_lines(document)
            blocks = scoped_blocks(lines, anchor) if self.require_anchor else ((0, lines),)
            for block_index, (start, block) in enumerate(blocks):
                anchor_offset = next(
                    (index for index, item in enumerate(block) if anchor in item.text),
                    None,
                )
                anchor_line = start + anchor_offset if anchor_offset is not None else None
                for line_index, line in enumerate(block):
                    if self.period_marker_required and re.search(r"\d{2,4}\s*期", line.text) is None:
                        continue
                    windows = _line_windows(block, line_index)
                    for window in windows:
                        for pattern_index, pattern in enumerate(self.patterns):
                            for match in pattern.finditer(window):
                                try:
                                    period = int(match.group(1).lstrip("0") or "0")
                                    zodiac = match.group(2)
                                except (IndexError, ValueError):
                                    continue
                                raw_match = normalize_space(match.group(0))
                                match_line_index, match_offset = _window_match_location(
                                    block,
                                    line_index,
                                    match.start(1),
                                )
                                absolute_line_index = start + match_line_index
                                line_location = document.page_order * 1_000_000 + absolute_line_index
                                key = _physical_match_key(
                                    document.source_id,
                                    absolute_line_index,
                                    match_offset,
                                    period,
                                    zodiac,
                                )
                                if key in seen:
                                    continue
                                seen.add(key)
                                record_status = (
                                    "incomplete"
                                    if _PENDING_DRAW_PATTERN.search(window)
                                    else "complete"
                                )
                                candidates.append(
                                    Candidate(
                                        period,
                                        zodiac,
                                        raw_match,
                                        document.source_id,
                                        line_location,
                                        (
                                            f"anchor:{anchor}",
                                            f"pattern:{pattern_index}",
                                            f"block:{block_index}",
                                            *(() if anchor_line is None else (f"anchor-line:{anchor_line}",)),
                                            f"block-range:{start}-{start + len(block)}",
                                            f"record-offset:{match_offset}",
                                            f"record-status:{record_status}",
                                        ),
                                        record_id=document.record_id,
                                    )
                                )
        candidates.sort(key=lambda candidate: candidate.page_order)
        if site.name in self.directional_cycle_sites:
            return _tag_annual_record_cycles(candidates)
        return tuple(candidates)


def _tag_annual_record_cycles(candidates: list[Candidate]) -> tuple[Candidate, ...]:
    by_document: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_document.setdefault(candidate.document_id, []).append(candidate)

    tagged: list[Candidate] = []
    for document_candidates in by_document.values():
        cycles: list[list[Candidate]] = [[]]
        previous_period: int | None = None
        for candidate in document_candidates:
            period = candidate.period
            wraps_year = previous_period is not None and (
                (previous_period <= 20 and period >= 100)
                or (previous_period >= 300 and period <= 20)
            )
            if wraps_year:
                cycles.append([])
            cycles[-1].append(candidate)
            previous_period = period
        if len(cycles) == 1:
            tagged.extend(document_candidates)
            continue
        tagged.extend(
            replace(
                candidate,
                evidence=(*candidate.evidence, f"record-cycle:{cycle_index}"),
            )
            for cycle_index, cycle in enumerate(cycles)
            for candidate in cycle
        )
    tagged.sort(key=lambda candidate: candidate.page_order)
    return tuple(tagged)


def _line_windows(lines: tuple[TextLine, ...], index: int) -> tuple[str, ...]:
    windows: list[str] = []
    combined: list[str] = []
    for following in lines[index : index + 3]:
        if combined and following.heading:
            break
        combined.append(following.text)
        windows.append(normalize_space(" ".join(combined)))
        if len(combined) == 1 and re.search(r"绝杀|絕殺|杀肖|殺肖|禁肖|一肖|必杀", following.text):
            break
    return tuple(windows)


class AnchoredSectionFamilyParser:
    def __init__(self, specs: Mapping[str, AnchoredSectionSpec]) -> None:
        self.specs = MappingProxyType(
            {
                name: _CompiledAnchoredSectionSpec(
                    re.compile(spec.anchor_pattern, re.IGNORECASE),
                    re.compile(spec.record_pattern, re.IGNORECASE),
                    re.compile(spec.stop_pattern, re.IGNORECASE) if spec.stop_pattern else None,
                    spec.include_anchor_line,
                    spec.record_window_lines,
                )
                for name, spec in specs.items()
            }
        )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        spec = self.specs.get(site.name)
        if spec is None:
            return ()
        candidates: list[Candidate] = []
        seen: set[tuple[str, int, int, int, str]] = set()
        for document in bundle.documents:
            lines = document_lines(document)
            for anchor_index, anchor_line in enumerate(lines):
                if spec.anchor_pattern.search(anchor_line.text) is None:
                    continue
                first_record_index = anchor_index if spec.include_anchor_line else anchor_index + 1
                end_index = len(lines)
                for index in range(first_record_index, len(lines)):
                    line = lines[index].text
                    if spec.stop_pattern is not None and spec.stop_pattern.search(line):
                        end_index = index
                        break
                    if index > anchor_index and spec.anchor_pattern.search(line):
                        end_index = index
                        break
                    record_text = normalize_space(
                        " ".join(
                            item.text
                            for item in lines[index : index + spec.record_window_lines]
                        )
                    )
                    for match in spec.record_pattern.finditer(record_text):
                        period = int(match.group(1).lstrip("0") or "0")
                        zodiac = match.group(2)
                        key = _physical_match_key(
                            document.source_id,
                            index,
                            match.start(1),
                            period,
                            zodiac,
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(
                            Candidate(
                                period,
                                zodiac,
                                record_text,
                                document.source_id,
                                document.page_order * 1_000_000 + index,
                                (
                                    f"section:{normalize_space(anchor_line.text)}",
                                    f"anchor:{normalize_space(anchor_line.text)}",
                                    f"anchor-line:{anchor_index}",
                                    f"section-range:{anchor_index}-{end_index}",
                                    f"record-offset:{match.start(1)}",
                                ),
                                record_id=document.record_id,
                            )
                        )
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)


class StrictArticleFamilyParser:
    def __init__(self, specs: Mapping[str, StrictArticleSpec]) -> None:
        self.specs = MappingProxyType(
            {
                name: _CompiledStrictArticleSpec(
                    re.compile(spec.title_pattern, re.IGNORECASE),
                    re.compile(spec.record_pattern, re.IGNORECASE),
                    re.compile(spec.author_pattern, re.IGNORECASE) if spec.author_pattern else None,
                    spec.allow_pending_title,
                    spec.directional_cycles,
                )
                for name, spec in specs.items()
            }
        )

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        spec = self.specs.get(site.name)
        if spec is None:
            return ()
        candidates: list[Candidate] = []
        for document in bundle.documents:
            lines = document_lines(document)
            for title_index, title_line in enumerate(lines):
                title_match = spec.title_pattern.search(title_line.text)
                if title_match is None:
                    continue
                author_text = _strict_author_text(lines, title_index, spec)
                if spec.author_pattern is not None and author_text is None:
                    continue
                author_line_index = _strict_author_line_index(lines, title_index, spec)
                title_period = int(title_match.group(1).lstrip("0") or "0")
                records = _strict_article_records(
                    document.source_id,
                    document.page_order,
                    document.record_id,
                    lines,
                    title_index,
                    title_period,
                    title_line.text,
                    author_line_index,
                    author_text,
                    spec,
                )
                accepted_title_periods = {title_period}
                if spec.allow_pending_title and title_period > 1:
                    accepted_title_periods.add(title_period - 1)
                for cycle_index, cycle in enumerate(_strict_cycles(records, title_period)):
                    eligible = tuple(
                        candidate for candidate in cycle if candidate.period <= title_period
                    )
                    accepted_indexes = [
                        index
                        for index, candidate in enumerate(cycle)
                        if candidate.period in accepted_title_periods
                    ]
                    if not eligible or not accepted_indexes:
                        continue
                    if any(candidate.period > title_period for candidate in cycle[: accepted_indexes[0]]):
                        continue
                    if spec.directional_cycles:
                        eligible = tuple(
                            replace(
                                candidate,
                                evidence=(
                                    *candidate.evidence,
                                    f"record-cycle:{title_index}:{cycle_index}",
                                ),
                            )
                            for candidate in eligible
                        )
                    candidates.extend(eligible)
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)


def _strict_cycles(
    candidates: tuple[Candidate, ...],
    title_period: int,
) -> tuple[tuple[Candidate, ...], ...]:
    cycles: list[tuple[Candidate, ...]] = []
    current: list[Candidate] = []
    previous_period: int | None = None
    for candidate in candidates:
        period = candidate.period
        reset = previous_period is not None and (
            (previous_period <= 20 and period > title_period)
            or (previous_period >= title_period and period <= 20)
        )
        if reset and current:
            cycles.append(tuple(current))
            current = []
        current.append(candidate)
        previous_period = period
    if current:
        cycles.append(tuple(current))
    return tuple(cycles)


def _strict_author_text(
    lines: tuple[TextLine, ...],
    title_index: int,
    spec: _CompiledStrictArticleSpec,
) -> str | None:
    if spec.author_pattern is None:
        return "not-required"
    author_index = _strict_author_line_index(lines, title_index, spec)
    if author_index is not None:
        return normalize_space(re.sub(r"^作者\s*[:：]\s*", "", lines[author_index].text))
    return None


def _strict_author_line_index(
    lines: tuple[TextLine, ...],
    title_index: int,
    spec: _CompiledStrictArticleSpec,
) -> int | None:
    if spec.author_pattern is None:
        return None
    for index in range(title_index + 1, min(len(lines), title_index + 5)):
        line = lines[index].text
        if spec.record_pattern.search(line) or _strict_boundary(lines, index, spec):
            break
        if spec.author_pattern.search(line):
            return index
    return None


def _strict_boundary(
    lines: tuple[TextLine, ...],
    index: int,
    spec: _CompiledStrictArticleSpec,
) -> bool:
    line = lines[index].text
    if spec.record_pattern.search(line) or re.search(r"\d{2,4}\s*期", line) is None:
        return False
    following = lines[index + 1 : index + 4]
    return bool(
        re.search(r"(?:一肖|壹肖|①肖)", line)
        or any(re.search(r"作者\s*[:：]", item.text) for item in following)
    )


def _strict_article_records(
    document_id: str,
    document_order: int,
    record_id: str | None,
    lines: tuple[TextLine, ...],
    title_index: int,
    title_period: int,
    title_text: str,
    author_line_index: int | None,
    author_text: str | None,
    spec: _CompiledStrictArticleSpec,
) -> tuple[Candidate, ...]:
    record_rows: list[tuple[int, str, str, int, int]] = []
    seen: set[tuple[str, int, int, int, str]] = set()
    block_end = len(lines)
    title_period_evidence = _title_period_evidence(title_text, title_period)
    for index in range(title_index + 1, len(lines)):
        line = lines[index].text
        if line.startswith(("上一篇", "下一篇")):
            block_end = index
            break
        matches = tuple(spec.record_pattern.finditer(line))
        if not matches and index > title_index and spec.title_pattern.search(line):
            block_end = index
            break
        if not matches:
            if _strict_boundary(lines, index, spec):
                block_end = index
                break
            continue
        for match in matches:
            period = int(match.group(1).lstrip("0") or "0")
            zodiac = match.group(2)
            key = _physical_match_key(
                document_id,
                index,
                match.start(1),
                period,
                zodiac,
            )
            if key in seen:
                continue
            seen.add(key)
            record_rows.append((period, zodiac, line, index, match.start(1)))

    return tuple(
        Candidate(
            period,
            zodiac,
            line,
            document_id,
            document_order * 1_000_000 + index,
            (
                f"title-text:{normalize_space(title_text)}",
                f"title-period:{title_period_evidence}",
                f"title-line:{title_index}",
                f"article-range:{title_index}-{block_end}",
                f"author:{author_text}",
                *(() if author_line_index is None else (f"author-line:{author_line_index}",)),
                f"record-offset:{match_offset}",
                "family:strict-article",
            ),
            record_id=record_id,
        )
        for period, zodiac, line, index, match_offset in record_rows
    )


def _title_period_evidence(title_text: str, title_period: int) -> str:
    match = re.search(r"(?<!\d)(\d{2,4})\s*期", title_text)
    if match is None:
        return str(title_period)
    return str(int(match.group(1)))


class TitleAuthorParser:
    def __init__(self, title_pattern: str, record_pattern: str) -> None:
        self.title_pattern = re.compile(title_pattern, re.IGNORECASE)
        self.record_pattern = re.compile(record_pattern, re.IGNORECASE)

    def parse(self, site: SiteConfig, bundle: SourceBundle) -> tuple[Candidate, ...]:
        candidates: list[Candidate] = []
        seen: set[tuple[str, int, int, int, str]] = set()
        for document in bundle.documents:
            lines = document_lines(document)
            for title_index, title_line in enumerate(lines):
                title = self.title_pattern.search(title_line.text)
                if title is None:
                    continue
                author = title.group(2)
                author_index = next(
                    (
                        index
                        for index in range(title_index + 1, min(len(lines), title_index + 6))
                        if re.search(
                            rf"(?:作者\s*[:：]\s*{re.escape(author)}|{re.escape(author)}\s+发表于)",
                            lines[index].text,
                            re.IGNORECASE,
                        )
                    ),
                    None,
                )
                if author_index is None:
                    continue
                block_end = len(lines)
                for index in range(author_index + 1, len(lines)):
                    line = lines[index].text
                    if re.search(r"上一篇|下一篇", line) or self.title_pattern.search(line):
                        block_end = index
                        break
                    if re.search(r"(?:作者\s*[:：]|\S+\s+发表于)", line):
                        block_end = index
                        break
                    for match in self.record_pattern.finditer(line):
                        period = int(match.group(1))
                        zodiac = match.group(2)
                        key = _physical_match_key(
                            document.source_id,
                            index,
                            match.start(1),
                            period,
                            zodiac,
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(
                            Candidate(
                                period,
                                zodiac,
                                line,
                                document.source_id,
                                document.page_order * 1_000_000 + index,
                                (
                                    f"title-text:{normalize_space(title_line.text)}",
                                    f"title-line:{title_index}",
                                    f"title-author:{author}",
                                    f"author-line:{author_index}",
                                    f"article-range:{title_index}-{block_end}",
                                    f"record-offset:{match.start(1)}",
                                ),
                                record_id=document.record_id,
                            )
                        )
        candidates.sort(key=lambda candidate: candidate.page_order)
        return tuple(candidates)
