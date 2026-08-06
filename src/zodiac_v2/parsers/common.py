from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from zodiac_v2.contracts import DocumentType, SourceDocument

_SPACE_PATTERN = re.compile(r"[\s\u3000]+")
_SCRIPT_BASE64_PATTERNS = (
    re.compile(r"strdecode\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)", re.IGNORECASE),
    re.compile(r"decodeB64\(\s*['\"]([A-Za-z0-9+/=]+)['\"]\s*\)", re.IGNORECASE),
    re.compile(r"__PAGE_DATA__\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", re.IGNORECASE),
)
_BLOCK_TAGS = frozenset({"article", "br", "div", "li", "p", "section", "td", "th", "tr"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "title"})
_TRADITIONAL_ZODIACS = str.maketrans({"馬": "马", "雞": "鸡", "豬": "猪", "龍": "龙"})
_AUTHOR_BOUNDARY_PATTERN = re.compile(r"(?:作者\s*[:：]|[^\s]{1,80}\s+发表于)")
_NAV_BOUNDARY_PATTERN = re.compile(r"上一篇|下一篇|站长宣言|目[标標]资料结束")
_PERIOD_PATTERN = re.compile(r"\d{2,4}\s*期")
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
_JSON_AUTHOR_FIELDS = frozenset({"authorNickname", "author", "authorName", "nickname"})


@dataclass(frozen=True, slots=True)
class TextLine:
    text: str
    heading: bool = False


def normalize_space(value: str) -> str:
    return _SPACE_PATTERN.sub(" ", value.translate(_TRADITIONAL_ZODIACS)).strip()


class _LineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[TextLine] = []
        self._parts: list[str] = []
        self._heading_depth = 0

    def _flush(self) -> None:
        text = normalize_space("".join(self._parts))
        if text:
            self.lines.append(TextLine(text, self._heading_depth > 0))
        self._parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in _BLOCK_TAGS or lowered in _HEADING_TAGS:
            self._flush()
        if lowered in _HEADING_TAGS:
            self._heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _BLOCK_TAGS or lowered in _HEADING_TAGS:
            self._flush()
        if lowered in _HEADING_TAGS and self._heading_depth:
            self._heading_depth -= 1

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


def text_lines(value: str) -> tuple[TextLine, ...]:
    parser = _LineParser()
    parser.feed(value)
    parser.close()
    return tuple(parser.lines)


def _json_strings(value: object) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
        decoded = _decode_base64_json_field(value)
        if decoded is not None:
            strings.append(decoded)
    elif isinstance(value, dict):
        ordered_keys = [key for key in _JSON_TEXT_FIELD_ORDER if key in value]
        ordered_keys.extend(key for key in value if key not in ordered_keys)
        for key in ordered_keys:
            field_strings = _json_strings(value[key])
            if key in _JSON_AUTHOR_FIELDS:
                field_strings = [f"作者:{item}" for item in field_strings]
            strings.extend(field_strings)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_json_strings(item))
    return strings


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


def decoded_script_fragments(value: str, *, preserve_duplicates: bool = False) -> tuple[str, ...]:
    fragments: list[str] = []
    seen: set[str] = set()
    for pattern in _SCRIPT_BASE64_PATTERNS:
        for encoded in pattern.findall(value):
            if not preserve_duplicates and encoded in seen:
                continue
            seen.add(encoded)
            try:
                fragments.append(base64.b64decode(encoded, validate=True).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
    return tuple(fragments)


def document_lines(document: SourceDocument) -> tuple[TextLine, ...]:
    values = [document.text]
    if document.document_type is DocumentType.JSON:
        try:
            values = _json_strings(json.loads(document.text))
        except json.JSONDecodeError:
            values = [document.text]

    lines: list[TextLine] = []
    for value in values:
        lines.extend(text_lines(value))
        for fragment in decoded_script_fragments(value):
            lines.extend(text_lines(fragment))
    return tuple(lines)


def scoped_blocks(lines: tuple[TextLine, ...], anchor: str) -> tuple[tuple[int, tuple[TextLine, ...]], ...]:
    anchor_indexes = [index for index, line in enumerate(lines) if anchor in line.text]
    blocks: list[tuple[int, tuple[TextLine, ...]]] = []
    for anchor_index in anchor_indexes:
        start = anchor_index
        if (
            anchor_index
            and _AUTHOR_BOUNDARY_PATTERN.search(lines[anchor_index].text)
            and _PERIOD_PATTERN.search(lines[anchor_index - 1].text)
        ):
            start -= 1
        end = len(lines)
        for index in range(anchor_index + 1, len(lines)):
            line = lines[index]
            if line.heading:
                end = index
                break
            if _NAV_BOUNDARY_PATTERN.search(line.text):
                end = index
                break
            if (
                index > anchor_index + 1
                and _AUTHOR_BOUNDARY_PATTERN.search(line.text)
                and anchor not in line.text
            ):
                end = index
                break
        block = lines[start:end]
        if block:
            blocks.append((start, block))
    return tuple(blocks)
