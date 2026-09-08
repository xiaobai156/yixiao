from __future__ import annotations

import re
from collections.abc import Iterable

from zodiac_v2.contracts import (
    ZODIACS,
    Candidate,
    Direction,
    FailureCode,
    SiteConfig,
    SourceBundle,
    SourceDocument,
    ValidationDecision,
)
from zodiac_v2.parsers.common import document_lines, normalize_space
from zodiac_v2.validation.direction import directional_candidate_window
from zodiac_v2.validation.evidence import validate_candidate_evidence


def _record_cycle_key(candidate: Candidate) -> tuple[str, str] | None:
    cycle = next(
        (item.partition(":")[2] for item in candidate.evidence if item.startswith("record-cycle:")),
        None,
    )
    return (candidate.document_id, cycle) if cycle is not None else None


def _active_candidates(items: tuple[Candidate, ...], direction: Direction) -> tuple[Candidate, ...]:
    if direction is Direction.LEFT:
        return items
    grouped: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in items:
        key = _record_cycle_key(candidate)
        if key is None:
            return items
        grouped.setdefault(key, []).append(candidate)
    if len(grouped) <= 1:
        return items
    ordered = sorted(grouped.values(), key=lambda group: min(item.page_order for item in group))
    selected = ordered[0] if direction is Direction.TOP else ordered[-1]
    return tuple(sorted(selected, key=lambda candidate: candidate.page_order))


_INVALID_FIELD_PATTERN = re.compile(
    r"(?:绝杀|絕殺)(?:一|①)?肖.*?[【\[]\s*(?P<value>[^【】\[\]\s]+)\s*[】\]]"
)


def _invalid_target_field_reason(
    site: SiteConfig,
    document: SourceDocument,
    target_period: int,
) -> str | None:
    anchors = tuple(
        anchor
        for anchor in (site.name, site.article_keyword)
        if isinstance(anchor, str) and anchor.strip()
    )
    if not anchors:
        return None
    period_pattern = re.compile(rf"(?<!\d)0*{target_period}\s*期(?!\d)")
    invalid: list[tuple[str, str]] = []
    for line in document_lines(document):
        text = normalize_space(line.text)
        if not period_pattern.search(text) or not any(anchor in text for anchor in anchors):
            continue
        match = _INVALID_FIELD_PATTERN.search(text)
        if match is None:
            continue
        value = normalize_space(match.group("value"))
        if value in ZODIACS:
            continue
        invalid.append((value, text))
    if not invalid:
        return None
    values = "/".join(dict.fromkeys(value for value, _line in invalid))
    raw_lines = "；".join(dict.fromkeys(line for _value, line in invalid))
    return (
        f"页面已找到指定 {target_period}期，但目标字段{values!r}不是合法生肖，禁止写入；"
        f"原始行：{raw_lines}"
    )


def _direction_window(
    items: tuple[Candidate, ...],
    direction: Direction,
    target_period: int,
) -> tuple[tuple[Candidate, ...], ValidationDecision | None]:
    if direction is not Direction.LEFT:
        items = tuple(
            candidate
            for candidate in items
            if not (
                candidate.period > target_period
                and "record-status:incomplete" in candidate.evidence
            )
        )
    active = _active_candidates(items, direction)
    window = directional_candidate_window(active, direction)
    matched = tuple(candidate for candidate in window if candidate.period == target_period)

    if direction is Direction.LEFT:
        if not matched:
            return window, ValidationDecision.failure(
                FailureCode.PERIOD,
                f"候选中未找到指定 {target_period}期",
            )
        return window, None

    if not matched:
        target_exists = any(candidate.period == target_period for candidate in active)
        location = (
            f"页面其他位置存在{target_period}期候选"
            if target_exists
            else f"页面候选中未找到{target_period}期"
        )
        edge_label = "首组" if direction is Direction.TOP else "尾组"
        edge = window[0] if direction is Direction.TOP else window[-1]
        return window, ValidationDecision.failure(
            FailureCode.DIRECTION,
            f"{direction.value}有效候选{edge_label}为 {edge.period}期，"
            f"不等于指定 {target_period}期；{location}，按方向边界丢失败",
        )

    edge = window[0] if direction is Direction.TOP else window[-1]
    if edge.period != target_period:
        edge_label = "首组" if direction is Direction.TOP else "尾组"
        return window, ValidationDecision.failure(
            FailureCode.DIRECTION,
            f"{direction.value}有效候选{edge_label}为 {edge.period}期，"
            f"不等于指定 {target_period}期，按方向边界丢失败",
        )
    return window, None


def _window_conflict(
    window: tuple[Candidate, ...],
    target_period: int,
) -> ValidationDecision | None:
    zodiacs: list[str] = []
    for candidate in window:
        if candidate.period != target_period or candidate.zodiac in zodiacs:
            continue
        zodiacs.append(candidate.zodiac)
    if len(zodiacs) > 1:
        return ValidationDecision.failure(
            FailureCode.CONFLICT,
            f"指定 {target_period}期存在多个合法候选：{'/'.join(zodiacs)}，禁止自动选择",
        )
    return None


def validate_candidates(
    site: SiteConfig,
    bundle: SourceBundle,
    candidates: Iterable[Candidate],
    target_period: int,
) -> ValidationDecision:
    if not bundle.scan_complete:
        diagnostics = "、".join(bundle.diagnostics) or "scan_complete:0"
        return ValidationDecision.failure(
            FailureCode.BOUNDARY,
            f"来源扫描未完成，禁止在文档截断时确认候选：{diagnostics}",
        )
    items = tuple(candidates)
    if not items:
        return ValidationDecision.failure(
            FailureCode.PERIOD,
            f"未找到任何候选，无法命中指定 {target_period}期",
        )

    lines_cache: dict[str, tuple[str, ...]] = {}
    for candidate in items:
        evidence_decision = validate_candidate_evidence(
            candidate,
            bundle,
            _lines_cache=lines_cache,
        )
        if not evidence_decision.ok:
            return evidence_decision

    candidates_by_document: dict[str, list[Candidate]] = {}
    documents_by_id = {document.source_id: document for document in bundle.documents}
    for candidate in items:
        candidates_by_document.setdefault(candidate.document_id, []).append(candidate)

    windows: dict[str, tuple[Candidate, ...]] = {}
    for document_id, document_candidates in candidates_by_document.items():
        window, direction_failure = _direction_window(
            tuple(document_candidates),
            site.direction,
            target_period,
        )
        if direction_failure is not None:
            document = documents_by_id.get(document_id)
            invalid_field_reason = (
                _invalid_target_field_reason(site, document, target_period)
                if document is not None
                else None
            )
            if invalid_field_reason is not None:
                if len(candidates_by_document) > 1:
                    invalid_field_reason = f"来源文档 {document_id} {invalid_field_reason}"
                return ValidationDecision.failure(FailureCode.FIELD, invalid_field_reason)
            if len(candidates_by_document) > 1:
                return ValidationDecision.failure(
                    direction_failure.failure_code or FailureCode.OTHER,
                    f"来源文档 {document_id} {direction_failure.reason}",
                )
            return direction_failure
        windows[document_id] = window

    for window in windows.values():
        conflict = _window_conflict(window, target_period)
        if conflict is not None:
            return conflict

    zodiacs: list[str] = []
    for window in windows.values():
        for candidate in window:
            if candidate.period != target_period or candidate.zodiac in zodiacs:
                continue
            zodiacs.append(candidate.zodiac)
    if len(zodiacs) > 1:
        return ValidationDecision.failure(
            FailureCode.CONFLICT,
            f"来源冲突：指定 {target_period}期存在多个合法候选："
            f"{'/'.join(zodiacs)}，禁止自动选择",
        )

    documents = {document.source_id: document for document in bundle.documents}
    matched_by_document = {
        document_id: tuple(
            candidate for candidate in window if candidate.period == target_period
        )
        for document_id, window in windows.items()
    }
    selected_document_id = min(
        matched_by_document,
        key=lambda document_id: (
            documents[document_id].priority,
            documents[document_id].page_order,
        ),
    )
    matched = matched_by_document[selected_document_id]
    selected = matched[-1] if site.direction is Direction.BOTTOM else matched[0]
    return ValidationDecision.success(selected)
