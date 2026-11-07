from __future__ import annotations

import base64
import json
import re
from contextlib import suppress
from html.parser import HTMLParser

from zodiac_v2.contracts import Candidate, DocumentType, FailureCode, SourceBundle, ValidationDecision, ZODIACS

_SPACE_PATTERN = re.compile(r"[\s\u3000]+")
_PERIOD_TOKEN_PATTERN = re.compile(r"(?<!\d)(第\s*)?(\d{1,4})\s*期")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# “本月第2期”这类序号标签最大只到 12；更大的“第309期”按真实期号处理。
_MAX_ORDINAL_LABEL = 12
# 期号后紧跟这些词是战绩说明，不是新记录。
_STREAK_NOTE_PATTERN = re.compile(r"\s*(?:连中|連中|连准|連準|全中|精准|精準|命中)")
# 期号后紧跟字段词（杀鸡/禁肖/必杀…）说明这个期号是记录本身，不能当说明豁免。
_FIELD_WORD_PATTERN = re.compile(r"[\s、，,。：:；;]*[杀殺禁绝絕必肖]")
# 期号前出现这些词说明是上一期/历史结果，整段豁免（含括号里的写法）。
_NOTE_MARKERS = ("上期", "往期", "前期", "上次", "前一期", "回查", "参考")
_NOTE_WINDOW = 8
# 少量站点写“310杀鸡”不带“期”字，用 3–4 位裸期号兜底。
_BARE_PERIOD_PATTERN = re.compile(r"(?<!\d)(\d{3,4})(?=\s*(?:杀|殺|禁|绝|絕|必))")
# 年份不是期号。
_YEAR_RANGE = range(1900, 2100)
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


def _derived_missing_zodiac_matches(candidate: Candidate) -> bool:
    if "derived:missing-zodiac" not in candidate.evidence:
        return False
    listed_match = re.search(r"[（(]([^）)]+)[）)]", candidate.raw_line)
    if listed_match is None:
        return False
    listed = tuple(character for character in listed_match.group(1) if character in ZODIACS)
    missing = ZODIACS.difference(listed)
    return len(listed) == 11 and len(set(listed)) == 11 and len(missing) == 1 and candidate.zodiac in missing


def _is_result_note(text: str, start: int, end: int, value: int, period: int) -> bool:
    """判断这个期号是不是上一期结果/战绩说明，而不是新记录的期号。"""
    if value == period:
        return False
    if _FIELD_WORD_PATTERN.match(text, end):
        return False
    if any(marker in text[max(0, start - _NOTE_WINDOW) : start] for marker in _NOTE_MARKERS):
        return True
    return _STREAK_NOTE_PATTERN.match(text, end) is not None


def _issue_period_tokens(text: str, period: int) -> list[int]:
    """返回文本里的期号；“本月第2期”序号和上期结果说明不算期号。"""
    tokens: list[int] = []
    for match in _PERIOD_TOKEN_PATTERN.finditer(text):
        prefix, number = match.group(1), match.group(2)
        value = int(number.lstrip("0") or "0")
        if prefix and value <= _MAX_ORDINAL_LABEL:
            continue
        if _is_result_note(text, match.start(), match.end(), value, period):
            continue
        tokens.append(value)
    return tokens


def _bare_period_tokens(text: str, period: int) -> list[int]:
    """不带“期”字的裸期号；年份不算，前置上期/参考等说明的也不算。"""
    values: list[int] = []
    for match in _BARE_PERIOD_PATTERN.finditer(text):
        value = int(match.group(1))
        if value in _YEAR_RANGE:
            continue
        if value != period and any(
            marker in text[max(0, match.start() - _NOTE_WINDOW) : match.start()] for marker in _NOTE_MARKERS
        ):
            continue
        values.append(value)
    return values


def _raw_line_owns_period(candidate: Candidate) -> bool:
    """为真表示原始行里生肖之前的期号都等于候选期数。

    跨行拼接窗口形如 ``310期资料更新中 309期 绝杀一肖【牛】``：期号仍停在开头，
    真正的记录属于另一个期数。生肖前出现其他期号时，值不属于本期，必须判失败。
    ``第309期`` 是真实期号，只有 ``本月第2期`` 这类小序号才豁免。
    """
    zodiac_index = candidate.raw_line.find(candidate.zodiac)
    if zodiac_index < 0:
        return True
    prefix = candidate.raw_line[:zodiac_index]
    values = _issue_period_tokens(prefix, candidate.period) + _bare_period_tokens(prefix, candidate.period)
    return all(value == candidate.period for value in values)


def _value_line_index(
    candidate: Candidate,
    lines: tuple[str, ...],
    local_position: int,
) -> int | None:
    """用原始行在文档里的位置偏移，定位生肖所在的物理行。"""
    window = 8
    joined = _normalize_space(" ".join(lines[local_position : local_position + window]))
    raw = _normalize_space(candidate.raw_line)
    offset = joined.find(raw)
    if offset < 0:
        return None
    zodiac_offset = raw.find(candidate.zodiac)
    if zodiac_offset < 0:
        return None
    target = offset + zodiac_offset
    cursor = 0
    for index in range(local_position, min(local_position + window, len(lines))):
        text = _normalize_space(lines[index])
        end = cursor + len(text)
        if target <= end:
            return index
        cursor = end + 1
    return None


def _declared_value_line(candidate: Candidate) -> int | None:
    for name in ("value-line", "record-line"):
        for evidence in candidate.evidence:
            prefix, _, value = evidence.partition(":")
            if prefix == name and value.strip().isdigit():
                return int(value)
    return None


def _is_cell_line(text: str) -> bool:
    """表格里“一格一行”的短行、以及 JS 拼接片段，不算记录间距。"""
    stripped = text.strip()
    if stripped.startswith(("document.write", "document.writeln")):
        return True
    return len(stripped) <= 12 and not any(mark in stripped for mark in "。！？；")


def _value_line_violation(
    candidate: Candidate,
    lines: tuple[str, ...],
    local_position: int,
) -> str | None:
    """期号必须落在值行或紧邻值行的行上；中间夹着整段正文说明则判失败。"""
    declared = _declared_value_line(candidate)
    if declared is not None:
        # 解析器已显式声明值行，归属由期号门禁负责；但声明行必须真的含这个值。
        if not 0 <= declared < len(lines):
            return f"声明的值行 {declared} 超出文档范围：{candidate.raw_line}"
        if "derived:missing-zodiac" not in candidate.evidence and candidate.zodiac not in lines[declared]:
            return f"声明的值行不含生肖 {candidate.zodiac}：{lines[declared][:60]}"
        return None
    value_line = _value_line_index(candidate, lines, local_position)
    if value_line is None or not local_position <= value_line < len(lines):
        return None
    token_line: int | None = None
    for index in range(local_position, value_line + 1):
        text = lines[index]
        if index == value_line:
            cut = text.find(candidate.zodiac)
            if cut >= 0:
                text = text[:cut]
        if _issue_period_tokens(text, candidate.period) or _bare_period_tokens(text, candidate.period):
            token_line = index
    if token_line is None or token_line >= value_line:
        return None
    gap = [index for index in range(token_line + 1, value_line) if not _is_cell_line(lines[index])]
    if len(gap) > 1:
        return f"候选期号行与值行之间夹了 {len(gap)} 行正文：{candidate.raw_line}"
    return None


def _verified_title_period(
    candidate: Candidate,
    lines: tuple[str, ...],
    local_position: int,
) -> bool:
    """True when a verified title-period/title-line pair proves the period.

    The title line is content-checked against the source document, the bound
    value must equal the candidate period, and one declared range must contain
    both the title line and the candidate position (same proven data block).
    """
    title_indexes: list[int] = []
    for evidence in candidate.evidence:
        if not evidence.startswith("title-line:"):
            continue
        value = evidence.partition(":")[2].strip()
        if not value.isdigit():
            return False
        index = int(value)
        if not 0 <= index < len(lines):
            return False
        title_indexes.append(index)
    if not title_indexes:
        return False
    bound = False
    for evidence in candidate.evidence:
        prefix, _, value = evidence.partition(":")
        if prefix != "title-period" or not value.strip().isdigit():
            continue
        if int(value) != candidate.period:
            continue
        if any(
            re.search(rf"(?<!\d)0*{value}\s*期(?!\d)", lines[index]) is not None
            for index in title_indexes
        ):
            bound = True
    if not bound:
        return False
    for evidence in candidate.evidence:
        prefix, _, value = evidence.partition(":")
        if prefix not in _RANGE_EVIDENCE_PREFIXES:
            continue
        parsed_range = _parse_evidence_range(value, len(lines))
        if parsed_range is None:
            continue
        start, end = parsed_range
        if any(start <= index < end for index in title_indexes) and start <= local_position < end:
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
    if candidate.record_id is not None and document.record_id is not None and candidate.record_id != document.record_id:
        return ValidationDecision.failure(FailureCode.SOURCE_IDENTITY, "候选记录 ID 与来源文档记录 ID 不一致")
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

    normalized_raw = candidate.raw_line.translate(_FULLWIDTH_DIGITS)
    if (
        re.search(rf"(?<!\d)0*{candidate.period}(?!\d)", normalized_raw) is None
        and not _verified_title_period(candidate, lines, local_position)
    ):
        return ValidationDecision.failure(
            FailureCode.FIELD,
            f"候选原始行不含自身期数 {candidate.period}：{candidate.raw_line}",
        )
    if candidate.zodiac not in candidate.raw_line and not _derived_missing_zodiac_matches(candidate):
        return ValidationDecision.failure(
            FailureCode.FIELD,
            f"候选原始行不含自身生肖 {candidate.zodiac}：{candidate.raw_line}",
        )
    if not _raw_line_owns_period(candidate):
        return ValidationDecision.failure(
            FailureCode.FIELD,
            f"候选原始行在生肖前出现其他期数：{candidate.raw_line}",
        )
    value_line_violation = _value_line_violation(candidate, lines, local_position)
    if value_line_violation is not None:
        return ValidationDecision.failure(FailureCode.FIELD, value_line_violation)

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

    if evidence_ranges:
        block_end = min(end for _prefix, _start, end in evidence_ranges)
        bounded_source = _normalize_space(" ".join(lines[local_position:min(local_position + 8, block_end)]))
        if expected not in bounded_source:
            return ValidationDecision.failure(FailureCode.BOUNDARY, "候选原始行跨越了已证明的区块结束边界")
    for prefix, start, end in evidence_ranges:
        if not start <= local_position < end:
            return ValidationDecision.failure(
                FailureCode.BOUNDARY,
                f"候选页内位置 {local_position} 不在 {prefix} {start}-{end} 内",
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
