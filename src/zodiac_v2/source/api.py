from __future__ import annotations

import json
import re
from time import monotonic
from urllib.parse import urlsplit

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.source.documents import SourceIdentityError, source_identity, validate_related_url
from zodiac_v2.source.http import (
    DEFAULT_MAX_BYTES,
    HttpTransport,
    SourceFetchCode,
    SourceFetchError,
    fetch_http_document,
)

_ARTICLE_PAGE_PATTERN = re.compile(
    r"^/article/(admin|manager|lottery)/([a-z0-9]+)(?:/|$)",
    re.IGNORECASE,
)
_USER_FORUM_API_PATTERN = re.compile(r"(?:^|/)api/v1/users/(\d+)/forums(?:/|$)", re.IGNORECASE)
_TOPIC_PERIOD_PATTERN = re.compile(r"^\s*(?:第\s*)?(\d{2,4})(?=\s|期(?:\s|$)|$)")


def derived_article_api_urls(page_url: str) -> tuple[str, ...]:
    source_identity(page_url)
    parsed = urlsplit(page_url)
    match = _ARTICLE_PAGE_PATTERN.match(parsed.path)
    if match is None:
        return ()
    kind, article_id = match.groups()
    normalized_kind = kind.lower()
    api_kinds = (
        ("manager", "admin")
        if normalized_kind == "lottery"
        else (normalized_kind, "manager" if normalized_kind == "admin" else "admin")
    )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return tuple(
        f"{origin}/api/proxy/{api_kind}-articles/{article_id}"
        for api_kind in api_kinds
    )


def derived_user_forum_api_url(page_url: str, *, per_page: int = 20) -> str | None:
    if isinstance(per_page, bool) or not isinstance(per_page, int) or not 1 <= per_page <= 100:
        raise ValueError("per_page 必须是 1 到 100 的整数")
    identity = source_identity(page_url)
    if identity.user_id is None:
        return None
    parsed = urlsplit(page_url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/api/v1/users/{identity.user_id}/forums?per_page={per_page}"
    validate_related_url(page_url, api_url, require_matching_id=True)
    return api_url


def fetch_user_forum_api(
    transport: HttpTransport,
    *,
    page_url: str,
    timeout: float = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
    per_page: int = 20,
) -> SourceBundle:
    api_url = derived_user_forum_api_url(page_url, per_page=per_page)
    if api_url is None:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "用户主页 URL 缺少用户 ID", url=page_url)
    try:
        document = fetch_http_document(
            transport,
            api_url,
            timeout=timeout,
            max_bytes=max_bytes,
            document_type=DocumentType.JSON,
            source_id=f"user-api:{source_identity(page_url).user_id}",
        )
        validate_related_url(page_url, document.final_url, require_matching_id=True)
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=api_url) from exc
    return SourceBundle(
        (document,),
        (f"user-api:200:per_page={per_page}", "scan_complete:1"),
        scan_complete=True,
    )


def bind_user_forum_target(
    page_url: str,
    bundle: SourceBundle,
    target_period: int,
) -> SourceBundle:
    """Bind a user-home source bundle to one exact requested-period forum record."""
    if isinstance(target_period, bool) or not isinstance(target_period, int) or not 1 <= target_period <= 9999:
        raise ValueError("期数必须是 1 到 9999 的整数")
    try:
        expected = source_identity(page_url)
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=page_url) from exc
    if expected.user_id is None:
        return bundle
    if not bundle.scan_complete:
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"用户 {expected.user_id} 的帖子列表取源不完整，无法唯一锁定 {target_period}期帖子",
            url=page_url,
        )

    matches: dict[str, tuple[dict[str, object], SourceDocument, str]] = {}
    conflicting_record_ids: set[str] = set()
    for document in bundle.documents:
        if document.document_type is not DocumentType.JSON:
            continue
        path_match = _USER_FORUM_API_PATTERN.search(urlsplit(document.final_url).path)
        if path_match is None or path_match.group(1) != expected.user_id:
            continue
        try:
            rows = json.loads(document.text)
        except json.JSONDecodeError:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_id = row.get("id")
            draw = row.get("draw")
            user = row.get("user")
            topic = row.get("topic")
            content = row.get("content")
            topic_period_match = (
                _TOPIC_PERIOD_PATTERN.match(topic) if isinstance(topic, str) else None
            )
            topic_period = int(topic_period_match.group(1)) if topic_period_match is not None else None
            period_matches = (
                topic_period == target_period
                if topic_period is not None
                else draw == target_period
            )
            if (
                row.get("status") != "published"
                or isinstance(record_id, bool)
                or not isinstance(record_id, (str, int))
                or not str(record_id).strip()
                or isinstance(draw, bool)
                or not period_matches
                or row.get("user_id") != int(expected.user_id)
                or not isinstance(user, dict)
                or user.get("id") != int(expected.user_id)
                or not isinstance(user.get("nickname"), str)
                or not user["nickname"].strip()
                or (
                    row.get("authorNickname") is not None
                    and row.get("authorNickname") != user.get("nickname")
                )
                or not isinstance(topic, str)
                or not topic.strip()
                or not isinstance(content, str)
                or not content.strip()
            ):
                continue
            record_id_text = str(record_id).strip()
            canonical = json.dumps(
                {
                    "id": record_id_text,
                    "status": row["status"],
                    "user_id": row["user_id"],
                    "draw": draw,
                    "topic": topic,
                    "content": content,
                    "author_id": user["id"],
                    "author_nickname": user["nickname"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            previous = matches.get(record_id_text)
            if previous is not None and previous[2] != canonical:
                conflicting_record_ids.add(record_id_text)
                continue
            matches.setdefault(record_id_text, (row, document, canonical))

    if conflicting_record_ids or len(matches) > 1:
        record_ids = sorted(set(matches) | conflicting_record_ids)
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"用户 {expected.user_id} 找到多个不同的 {target_period}期帖子：{record_ids}",
            url=page_url,
        )
    if not matches:
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"用户 {expected.user_id} 的接口未找到指定 {target_period}期帖子",
            url=page_url,
        )

    record_id, (row, source, _canonical) = next(iter(matches.items()))
    selected_user = row.get("user")
    if not isinstance(selected_user, dict) or not isinstance(selected_user.get("nickname"), str):
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"用户 {expected.user_id} 的 {target_period}期帖子缺少作者身份",
            url=page_url,
        )
    projected_row = dict(row)
    projected_row["authorNickname"] = selected_user["nickname"]
    selected = SourceDocument(
        json.dumps([projected_row], ensure_ascii=False, separators=(",", ":")),
        source.final_url,
        DocumentType.JSON,
        source.priority,
        f"user:{expected.user_id}:record:{record_id}",
        0,
        record_id,
    )
    return SourceBundle(
        (selected,),
        (*bundle.diagnostics, f"user-forum-target:{target_period}", f"user-forum-record:{record_id}"),
        scan_complete=True,
    )


def fetch_api_then_page(
    transport: HttpTransport,
    *,
    api_url: str,
    page_url: str,
    timeout: float = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SourceBundle:
    deadline = monotonic() + timeout

    def remaining() -> float:
        seconds = deadline - monotonic()
        if seconds <= 0:
            raise SourceFetchError(
                SourceFetchCode.NETWORK,
                f"API/页面取源总超时 {timeout:g}秒",
                url=page_url,
            )
        return seconds

    try:
        page_identity = source_identity(page_url)
        validate_related_url(page_url, api_url, require_matching_id=page_identity.has_record_id)
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=api_url) from exc

    try:
        api_document = fetch_http_document(
            transport,
            api_url,
            timeout=remaining(),
            max_bytes=max_bytes,
            document_type=DocumentType.JSON,
            source_id=f"api:{page_identity.article_id or api_url}",
        )
    except SourceFetchError as exc:
        if exc.code is not SourceFetchCode.HTTP_STATUS or exc.status != 404:
            raise
    else:
        remaining()
        return SourceBundle((api_document,), ("api:200", "scan_complete:1"), scan_complete=True)

    page_document = fetch_http_document(
        transport,
        page_url,
        timeout=remaining(),
        max_bytes=max_bytes,
        document_type=DocumentType.HTML,
        source_id=f"page:{page_identity.article_id or page_url}",
    )
    remaining()
    return SourceBundle(
        (page_document,),
        ("api:404", "page:200", "scan_complete:1"),
        scan_complete=True,
    )
