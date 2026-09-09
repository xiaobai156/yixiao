"""Project an API envelope to records whose identity is locally provable.

Only named envelope fields are traversed. A matching id buried in metadata,
recommendations, an author object or a different row never authorizes a body.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from zodiac_v2.source.documents import SourceIdentity, SourceIdentityError, source_identity

_ENVELOPES = ("data", "items", "results", "records", "result")
_BODY_FIELDS = frozenset({"content", "body", "html", "text"})
_ID_KEYS = {
    "topic": frozenset({"topicid", "threadid"}),
    "article": frozenset({"articleid", "postid", "recordid"}),
    "user": frozenset({"userid", "uid", "memberid", "authorid"}),
}


def _id(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip() or None


def _canonical(row: object) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _records(value: object, depth: int = 0) -> Iterator[dict[str, object]]:
    if depth > 8:
        raise SourceIdentityError("接口记录容器嵌套超过上限")
    if isinstance(value, list):
        for item in value:
            yield from _records(item, depth + 1)
    elif isinstance(value, dict):
        if _BODY_FIELDS.intersection(value):
            yield value
        else:
            for key in _ENVELOPES:
                if key in value:
                    yield from _records(value[key], depth + 1)


def _matches(row: dict[str, object], kind: str, expected: str) -> bool:
    values = [
        _id(value) for key, value in row.items()
        if re.sub(r"[^a-z0-9]", "", key.lower()) in _ID_KEYS[kind]
    ]
    if kind == "user":
        author = row.get("user")
        if isinstance(author, dict) and "id" in author:
            values.append(_id(author["id"]))
        # A post's own id is never its author's id.
        return bool(values) and all(value == expected for value in values)
    if not values:
        values = [_id(row.get("id"))]
    return all(value == expected for value in values)


_RECORD_FIELDS = frozenset({
    "id", "articleid", "postid", "recordid", "topicid", "threadid",
    "userid", "uid", "memberid", "authorid", "title", "topic", "draw", "status",
    "authornickname", "author", "authorname", "nickname", "name", "user",
    "html", "content", "body", "text",
})


def _project_record(row: dict[str, object]) -> dict[str, object]:
    output = {}
    for key, value in row.items():
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized not in _RECORD_FIELDS:
            continue
        if normalized in {"user", "author"} and isinstance(value, dict):
            value = {name: item for name, item in value.items()
                     if name in {"id", "nickname", "name"} and isinstance(item, (str, int))}
        elif isinstance(value, (dict, list)):
            continue
        output[key] = value
    return output


def project_response(body: str, expected: SourceIdentity, response_url: str) -> str | None:
    """Return the authorized body, or None for a non-matching response.

    Article/topic sources require one unique record. A user-list source keeps
    that user's records only; the existing period/post binder selects the post.
    Conflicting copies of one id are errors, not a first/last-record decision.
    """
    related = source_identity(response_url)
    if any(wanted is not None and actual is not None and wanted != actual for wanted, actual in (
        (expected.article_id, related.article_id),
        (expected.topic_id, related.topic_id),
        (expected.user_id, related.user_id),
    )):
        return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise SourceIdentityError("接口返回非可信 JSON") from exc
    if not isinstance(payload, (dict, list)):
        raise SourceIdentityError("接口记录容器不是对象或数组")
    if not expected.has_record_id:
        return _canonical(payload)
    matches: dict[str, dict[str, object]] = {}
    by_id: dict[str, str] = {}
    for row in _records(payload):
        if any(wanted is not None and not _matches(row, kind, wanted) for kind, wanted in (
            ("article", expected.article_id), ("topic", expected.topic_id), ("user", expected.user_id),
        )):
            continue
        if any(row[key] is not None and not isinstance(row[key], str) for key in _BODY_FIELDS.intersection(row)):
            raise SourceIdentityError("目标接口记录正文字段类型非法")
        canonical = _canonical(row)
        record_id = _id(row.get("id"))
        if expected.user_id is not None and record_id is None:
            raise SourceIdentityError("目标用户帖子缺少稳定记录 ID")
        if record_id is not None:
            previous = by_id.get(record_id)
            if previous is not None and previous != canonical:
                raise SourceIdentityError("目标接口记录同 ID 内容冲突")
            by_id[record_id] = canonical
        matches.setdefault(canonical, _project_record(row))
    if not matches:
        return None
    if expected.article_id is not None or expected.topic_id is not None:
        if len(matches) != 1:
            raise SourceIdentityError("目标文章/主题接口出现多个不同记录，无法唯一投影")
        return _canonical(next(iter(matches.values())))
    return _canonical(list(matches.values()))
