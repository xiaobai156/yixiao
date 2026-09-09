"""Project structured responses without borrowing IDs from nested recommendations."""
from __future__ import annotations

import json

from zodiac_v2.source.documents import SourceIdentity, SourceIdentityError


class IdentityRecordMissing(SourceIdentityError):
    pass


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip() or None


def _records(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _records(item)
    elif isinstance(payload, dict):
        if any(key in payload for key in ('content', 'body', 'html', 'text')):
            yield payload
            return
        for key in ('data', 'items', 'records', 'results', 'article', 'post', 'topic', 'forums'):
            if key in payload:
                yield from _records(payload[key])


def project_response_record(body: str, expected: SourceIdentity) -> str:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise SourceIdentityError('身份绑定接口不是可信 JSON') from exc
    matches = []
    for record in _records(payload):
        if expected.article_id is not None:
            identifiers = [_id(record[key]) for key in ('article_id', 'articleId', 'post_id', 'record_id', 'id') if key in record]
            matched = bool(identifiers) and all(value == expected.article_id for value in identifiers)
        elif expected.topic_id is not None:
            identifiers = [_id(record[key]) for key in ('topic_id', 'topicId', 'thread_id', 'id') if key in record]
            matched = bool(identifiers) and all(value == expected.topic_id for value in identifiers)
        elif expected.user_id is not None:
            owners = [_id(record[key]) for key in ('user_id', 'userId', 'author_id', 'uid') if key in record]
            user = record.get('user')
            if isinstance(user, dict) and 'id' in user:
                owners.append(_id(user['id']))
            matched = bool(owners) and all(value == expected.user_id for value in owners)
        else:
            raise IdentityRecordMissing('页面没有可投影的记录身份')
        if matched:
            matches.append(record)
    if not matches:
        raise IdentityRecordMissing('接口未找到属于目标身份的正文记录')
    unique = {json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')): record for record in matches}
    if expected.article_id is not None or expected.topic_id is not None:
        if len(unique) != 1:
            raise SourceIdentityError('同一目标 ID 的接口正文记录冲突')
        return next(iter(unique))
    # User feeds legitimately contain several posts. Only this user's rows are
    # forwarded; bind_user_forum_target subsequently selects the requested issue.
    by_id = {}
    for canonical, record in unique.items():
        record_id = _id(record.get('id'))
        if record_id is None:
            raise SourceIdentityError('用户接口正文缺少稳定帖子 ID')
        if record_id in by_id and by_id[record_id] != canonical:
            raise SourceIdentityError('同一用户帖子 ID 的接口正文记录冲突')
        by_id[record_id] = canonical
    return json.dumps(list(unique.values()), ensure_ascii=False, separators=(',', ':'))
