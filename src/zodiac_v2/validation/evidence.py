from __future__ import annotations

import base64
import json
import re
from contextlib import suppress
from html.parser import HTMLParser

from zodiac_v2.contracts import Candidate, DocumentType, FailureCode, SourceBundle, ValidationDecision

_SPACE_PATTERN = re.compile(r"[\s\u3000]+")
_TRADITIONAL_ZODIACS = str.maketrans({"馬": "马", "雞": "鸡", "豬": "猪", "龍": "龙"})
_BLOCK_TAGS = frozenset({"article", "br", "div", "li", "p", "section", "td", "th", "tr"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "title"})
_SCRIPT_BASE64_PATTERNS = (
    re.compile(r"strdecode\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)", re.IGNORECASE),
    re.compile(r"decodeB64\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)", re.IGNORECASE),
    re.compile(r"__PAGE_DATA__\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", re.IGNORECASE),
)
_JSON_TEXT_FIELD_ORDER = (
    "title",
    "authorNickname",
    "author",
    "authorName",
    "nickname",
    "name",
    "html",
    "content",
    "body",
    "text",
)


def _normalize_space(value: str) -> str:
    return _SPACE_PATTERN.sub(" ", value.translate(_TRADITIONAL_ZODIACS)).strip()


class _LineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._parts: list[str] = []

    def _flush(self) -> None:
        text = _normalize_space("".join(self._parts))
        if text:
            self.lines.append(text)
        self._parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS or tag.lower() in _HEADING_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _BLOCK_TAGS or tag.lower() in _HEADING_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        pieces = data.splitlines()
        for index, piece in enumerate(pieces):
            if index:
                self._flush()
            if piece.strip():
                self._parts.append(piece)

    def close(self) -> None:
        super().close()
        self._flush()


def _text_lines(value: str) -> tuple[str, ...]:
    parser = _LineParser()
    parser.feed(value)
    parser.close()
    return tuple(parser.lines)


def _json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        strings = [value]
        decoded = _decode_base64_json_field(value)
        if decoded is not None:
            strings.append(decoded)
        return strings
    if isinstance(value, dict):
        keys = [key for key in _JSON_TEXT_FIELD_ORDER if key in value]
        keys.extend(key for key in value if key not in keys)
        output: list[str] = []
        for key in keys:
            values = _json_strings(value[key])
            if key in {"authorNickname", "author", "authorName", "nickname"}:
                values = [f"作者:{item}" for item in values]
            output.extend(values)
        return output
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_json_strings(item))
        return output
    return []


def _decode_base64_json_field(value: str) -> str | None:
    compact = value.strip()
    if len(compact) < 16 or len(compact) % 4 or re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact) is None:
        return None
    try:
        raw = base64.b64decode(compact, validate=True)
    except ValueError:
        return None
    for encoding in ("utf-8", "gb18030"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        visible = sum(character.isprintable() or character.isspace() for character in decoded)
        meaningful = re.search(r"[\u4e00-\u9fff]|<[^>]+>|\d{2,4}\s*期", decoded)
        if decoded and visible / len(decoded) >= 0.9 and meaningful:
            return decoded
    return None


def _decoded_script_fragments(value: str) -> tuple[str, ...]:
    fragments: list[str] = []
    seen: set[str] = set()
    for pattern in _SCRIPT_BASE64_PATTERNS:
        for encoded in pattern.findall(value):
            if encoded in seen:
                continue
            seen.add(encoded)
            try:
                fragments.append(base64.b64decode(encoded, validate=True).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
    return tuple(fragments)


def _document_lines(document) -> tuple[str, ...]:
    values = [document.text]
    if document.document_type is DocumentType.JSON:
        with suppress(json.JSONDecodeError):
            values = _json_strings(json.loads(document.text))
    lines: list[str] = []
    for value in values:
        lines.extend(_text_lines(value))
        for fragment in _decoded_script_fragments(value):
            lines.extend(_text_lines(fragment))
    return tuple(lines)

_BLOCK_EVIDENCE_PREFIXES = (
    "anchor:",
    "author:",
    "block:",
    "column:",
    "heading:",
    "record-name:",
    "section:",
    "site:",
    "tab-content:",
    "table-columns:",
    "title:",
    "title-author:",
    "title-text:",
)
_TEXT_EVIDENCE_PREFIXES = {
    "anchor",
    "author",
    "column",
    "heading",
    "record-name",
    "section",
    "site",
    "tab-content",
    "title",
    "title-period",
    "title-author",
    "title-text",
}
_LINE_EVIDENCE_PREFIXES = frozenset({"anchor-line", "author-line", "title-line"})
_RANGE_EVIDENCE_PREFIXES = frozenset(
    {"article-range", "block-range", "post-range", "section-range"}
)
_TOPIC_PERIOD_PATTERN = re.compile(r"^\s*(?:第\s*)?(\d{2,4})(?=\s|期(?:\s|$)|$)")


def _parse_evidence_index(prefix: str, value: str, line_count: int) -> int | None:
    if not value.isdigit():
        return None
    index = int(value)
    return index if 0 <= index < line_count else None


def _parse_evidence_range(value: str, line_count: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)-(\d+)", value.strip())
    if match is None:
        return None
    start, end = (int(item) for item in match.groups())
    if start < end <= line_count:
        return start, end
    return None


def _json_objects(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


def _dynamic_record_matches(document_text: str, candidate: Candidate) -> bool:
    if candidate.record_id is None:
        return False
    try:
        payload = json.loads(document_text)
    except (json.JSONDecodeError, TypeError):
        return False
    expected_raw = _normalize_space(candidate.raw_line)
    topic_period_markers = [
        item.partition(":")[2]
        for item in candidate.evidence
        if item.startswith("topic-period:")
    ]
    for item in _json_objects(payload):
        raw_id = item.get("id")
        if raw_id is None or str(raw_id).strip() != candidate.record_id:
            continue
        draw = item.get("draw")
        if topic_period_markers:
            if len(topic_period_markers) != 1 or not topic_period_markers[0].isdigit():
                continue
            if int(topic_period_markers[0]) != candidate.period:
                continue
            topic = item.get("topic")
            topic_match = _TOPIC_PERIOD_PATTERN.match(topic) if isinstance(topic, str) else None
            if topic_match is None or int(topic_match.group(1)) != candidate.period:
                continue
        elif isinstance(draw, bool) or not isinstance(draw, int) or draw != candidate.period:
            continue
        visible_lines = (
            _normalize_space(line)
            for value in _json_strings(item)
            for line in _text_lines(value)
        )
        if any(expected_raw in line for line in visible_lines):
            return True
    return False


def validate_candidate_evidence(
    candidate: Candidate,
    bundle: SourceBundle,
    *,
    _lines_cache: dict[str, tuple[str, ...]] | None = None,
) -> ValidationDecision:
    documents = [document for document in bundle.documents if document.source_id == candidate.document_id]
    if len(documents) != 1:
        detail = "未找到" if not documents else "存在多个"
        return ValidationDecision.failure(
            FailureCode.SOURCE_IDENTITY,
            f"候选来源身份 {candidate.document_id} {detail}对应文档",
        )

    document = documents[0]
    if document.record_id is not None and (
        (candidate.record_id is not None and candidate.record_id != document.record_id)
        or (document.document_type is DocumentType.JSON and candidate.record_id is None)
    ):
        return ValidationDecision.failure(
            FailureCode.SOURCE_IDENTITY,
            "候选记录 ID 与已绑定的来源文档记录 ID 不一致",
        )
    candidate_document_order = candidate.page_order // 1_000_000
    if candidate_document_order != document.page_order:
        return ValidationDecision.failure(
            FailureCode.BOUNDARY,
            f"候选页序 {candidate_document_order} 不匹配来源文档页序 {document.page_order}",
        )

    if _lines_cache is None:
        lines = _document_lines(document)
    else:
        lines = _lines_cache.get(document.source_id)
        if lines is None:
            lines = _document_lines(document)
            _lines_cache[document.source_id] = lines
    local_position = candidate.page_order % 1_000_000
    if local_position >= len(lines):
        return ValidationDecision.failure(
            FailureCode.BOUNDARY,
            f"候选页内位置 {local_position} 超出来源文档有效范围 {len(lines)}",
        )

    if re.search(rf"(?<!\d)0*{candidate.period}(?!\d)", candidate.raw_line) is None:
        return ValidationDecision.failure(
            FailureCode.FIELD,
            f"候选原始行不含自身期数 {candidate.period}：{candidate.raw_line}",
        )
    if candidate.zodiac not in candidate.raw_line:
        return ValidationDecision.failure(
            FailureCode.FIELD,
            f"候选原始行不含自身生肖 {candidate.zodiac}：{candidate.raw_line}",
        )

    expected = _normalize_space(candidate.raw_line)
    source_window = _normalize_space(" ".join(lines[local_position : local_position + 8]))
    evidence_window = _normalize_space(
        " ".join(lines[max(0, local_position - 8) : local_position + 9])
    )
    if expected not in source_window:
        return ValidationDecision.failure(
            FailureCode.BOUNDARY,
            f"候选原始行未在来源文档同块出现：{candidate.raw_line}",
        )
    if any(item.startswith("heading:forum-draw:") for item in candidate.evidence) and not _dynamic_record_matches(
        document.text, candidate
    ):
        return ValidationDecision.failure(
            FailureCode.ANCHOR,
            "动态帖子期数、帖子 ID 与候选原始行未在同一 JSON 记录中出现",
        )
    line_indexes: dict[str, int] = {}
    evidence_ranges: list[tuple[str, int, int]] = []
    for evidence in candidate.evidence:
        prefix, _, value = evidence.partition(":")
        if prefix == "block" and not value.strip().isdigit():
            return ValidationDecision.failure(
                FailureCode.ANCHOR,
                f"候选分块证据不是结构化编号：{evidence}",
            )
        if prefix == "tab-content" and value.strip().isdigit():
            # The tab id is an HTML attribute used to bind the navigation
            # item to its decoded content block; it is not visible text.
            continue
        if prefix in _LINE_EVIDENCE_PREFIXES:
            index = _parse_evidence_index(prefix, value.strip(), len(lines))
            if index is None:
                return ValidationDecision.failure(
                    FailureCode.ANCHOR,
                    f"候选行号证据无效：{evidence}",
                )
            line_indexes[prefix] = index
        if prefix in _RANGE_EVIDENCE_PREFIXES:
            parsed_range = _parse_evidence_range(value, len(lines))
            if parsed_range is None:
                return ValidationDecision.failure(
                    FailureCode.BOUNDARY,
                    f"候选区块范围证据无效：{evidence}",
                )
            evidence_ranges.append((prefix, *parsed_range))
        if prefix == "post" and (candidate.record_id is None or value.strip() != candidate.record_id):
            return ValidationDecision.failure(
                FailureCode.SOURCE_IDENTITY,
                "动态帖子证据缺少与候选一致的稳定帖子 ID",
            )
    if not any(item.startswith(_BLOCK_EVIDENCE_PREFIXES) for item in candidate.evidence):
        return ValidationDecision.failure(
            FailureCode.ANCHOR,
            f"候选缺少可追溯的栏目、标题、作者或分块证据：{candidate.evidence}",
        )

    for prefix, start, end in evidence_ranges:
        if not start <= local_position < end:
            return ValidationDecision.failure(
                FailureCode.BOUNDARY,
                f"候选页内位置 {local_position} 不在 {prefix} {start}-{end} 内",
            )

    for prefix, _start, end in evidence_ranges:
        bounded_source = _normalize_space(" ".join(lines[local_position:min(local_position + 8, end)]))
        if expected not in bounded_source:
            return ValidationDecision.failure(
                FailureCode.BOUNDARY,
                f"候选原始行跨出 {prefix} 声明的区块终点 {end}",
            )

    for evidence in candidate.evidence:
        prefix, _, value = evidence.partition(":")
        if prefix not in _TEXT_EVIDENCE_PREFIXES or not value:
            continue
        if prefix == "tab-content" and value.strip().isdigit():
            continue
        if prefix == "author" and value == "not-required":
            continue
        if prefix == "heading" and value.startswith("forum-draw:"):
            continue
        if prefix == "title-period":
            title_line_index = line_indexes.get("title-line")
            title_text = (
                lines[title_line_index]
                if title_line_index is not None
                else evidence_window
            )
            if re.search(rf"(?<!\d)0*{re.escape(value)}\s*期(?!\d)", title_text) is None:
                return ValidationDecision.failure(
                    FailureCode.ANCHOR,
                    f"候选标题期数 {value} 未在标题证据行出现，禁止使用伪造证据",
                )
            continue
        if prefix == "title-text":
            title_line_index = line_indexes.get("title-line")
            haystack = (
                lines[title_line_index]
                if title_line_index is not None
                else evidence_window
            )
            if _normalize_space(value) not in _normalize_space(haystack):
                return ValidationDecision.failure(
                    FailureCode.ANCHOR,
                    f"候选标题 {value!r} 未在标题证据行出现，禁止使用伪造证据",
                )
            continue
        if prefix == "title":
            value, _, title_period = value.partition("/")
            if (
                title_period
                and title_period.isdigit()
                and re.search(rf"(?<!\d){re.escape(title_period)}\s*期(?!\d)", evidence_window)
                is None
            ):
                return ValidationDecision.failure(
                    FailureCode.ANCHOR,
                    f"候选标题期数 {title_period} 未在来源文档同块出现，禁止使用伪造证据",
                )
        line_prefix = {
            "anchor": "anchor-line",
            "section": "anchor-line",
            "author": "author-line",
            "title-author": "author-line",
            "title": "title-line",
        }.get(prefix)
        haystack = (
            lines[line_indexes[line_prefix]]
            if line_prefix is not None and line_prefix in line_indexes
            else evidence_window
        )
        if _normalize_space(value) and _normalize_space(value) not in _normalize_space(haystack):
            return ValidationDecision.failure(
                FailureCode.ANCHOR,
                f"候选锚点 {value!r} 未在来源文档中出现，禁止使用伪造证据",
            )
    return ValidationDecision.success(candidate)
