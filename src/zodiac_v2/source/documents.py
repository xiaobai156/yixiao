from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, urljoin, urlsplit

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument

_TOPIC_PATTERN = re.compile(r"(?:^|/)topic/(\d+)(?:\.html)?(?:/|$)", re.IGNORECASE)
_USER_PATTERN = re.compile(r"(?:^|/)users/(\d+)(?:/|$)", re.IGNORECASE)
_ARTICLE_PATTERN = re.compile(
    r"(?:^|/)article/(?:admin|manager|lottery)/([a-z0-9]+)(?:/|$)",
    re.IGNORECASE,
)
_AR_CONTENT_PATTERN = re.compile(r"(?:^|/)article/ar_content/id/(\d+)(?:/|$)", re.IGNORECASE)
_ARTICLE_API_PATTERN = re.compile(
    r"(?:^|/)api/proxy/(?:admin-articles|manager-articles)/([a-z0-9]+)(?:/|$)",
    re.IGNORECASE,
)
_STATIC_ARTICLE_PATTERN = re.compile(
    r"(?:^|/)(art_zhuanqu|art_gsb|bbs)/([a-z0-9]+)(?:\.html)?(?:/|$)",
    re.IGNORECASE,
)
_QUERY_TOPIC_KEYS = {"topic.php": "id", "read.php": "tid"}
_QUERY_ARTICLE_KEYS = {
    "article.aspx": ("id", "article-aspx"),
    "bbs.aspx": ("id", "bbs-aspx"),
    "gsb.aspx": ("id", "gsb-aspx"),
    "gsb1.aspx": ("id", "gsb1-aspx"),
}
_DEFAULT_DOCUMENTS = frozenset({"index.html", "index.htm", "index.php", "index.aspx", "default.html", "default.htm", "default.aspx"})
_DYNAMIC_SCRIPT_SOURCE_PATTERN = re.compile(r"\bsrc\s*=\s*['\"]([^'\"<>]+)", re.IGNORECASE)
_NON_TEXT_ASSET_SUFFIXES = (
    ".avif", ".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp",
    ".mp3", ".mp4", ".ogg", ".wav", ".woff", ".woff2",
)


class SourceIdentityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    origin: str
    topic_id: str | None = None
    user_id: str | None = None
    article_id: str | None = None
    record_kind: str | None = None

    @property
    def has_record_id(self) -> bool:
        return any((self.topic_id, self.user_id, self.article_id))


@dataclass(frozen=True, slots=True)
class DiscoveredDocument:
    url: str
    document_type: DocumentType
    page_order: int


def _origin(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SourceIdentityError(f"来源 URL 非法：{url!r}") from exc
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise SourceIdentityError(f"来源 URL 非法：{url!r}")
    normalized_port = port or (443 if scheme == "https" else 80)
    return f"{scheme}://{hostname}:{normalized_port}", parsed.path + "/" + parsed.fragment


def _single_query_value(parsed, key: str) -> str | None:
    values = parse_qs(parsed.query, keep_blank_values=True).get(key, ())
    if len(values) != 1:
        return None
    value = values[0].strip()
    return value or None


def _canonical_path(path: str) -> str:
    normalized = path or "/"
    if normalized != "/":
        normalized = normalized.rstrip("/") or "/"
    basename = normalized.rsplit("/", 1)[-1].lower()
    if basename in _DEFAULT_DOCUMENTS:
        parent = normalized.rsplit("/", 1)[0]
        return parent or "/"
    return normalized


def _canonical_locator(url: str) -> tuple[str, tuple[tuple[str, str], ...], str]:
    parsed = urlsplit(url)
    return (
        _canonical_path(parsed.path),
        tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True))),
        parsed.fragment.rstrip("/"),
    )


def source_identity(url: str) -> SourceIdentity:
    origin, searchable = _origin(url)
    parsed = urlsplit(url)
    path_name = parsed.path.rstrip("/").rsplit("/", 1)[-1].lower()
    topic_match = _TOPIC_PATTERN.search(searchable)
    user_match = _USER_PATTERN.search(searchable)
    dynamic_article_match = _ARTICLE_PATTERN.search(searchable)
    ar_content_match = _AR_CONTENT_PATTERN.search(searchable)
    article_api_match = _ARTICLE_API_PATTERN.search(searchable)
    static_article_match = _STATIC_ARTICLE_PATTERN.search(searchable)
    query_topic_id = _single_query_value(parsed, _QUERY_TOPIC_KEYS[path_name]) if path_name in _QUERY_TOPIC_KEYS else None
    query_article_id = None
    query_article_kind = None
    if path_name in _QUERY_ARTICLE_KEYS:
        key, query_article_kind = _QUERY_ARTICLE_KEYS[path_name]
        query_article_id = _single_query_value(parsed, key)

    article_id = None
    record_kind = None
    if dynamic_article_match is not None:
        article_id = dynamic_article_match.group(1)
        record_kind = "dynamic-article"
    elif article_api_match is not None:
        article_id = article_api_match.group(1)
        record_kind = "dynamic-article"
    elif ar_content_match is not None:
        article_id = ar_content_match.group(1)
        record_kind = "ar-content"
    elif static_article_match is not None:
        record_kind = static_article_match.group(1).lower()
        article_id = static_article_match.group(2)
    elif query_article_id is not None:
        article_id = query_article_id
        record_kind = query_article_kind

    topic_id = topic_match.group(1) if topic_match else query_topic_id
    if topic_id is not None:
        record_kind = "topic"
    if user_match is not None:
        record_kind = "user"
    return SourceIdentity(
        origin=origin,
        topic_id=topic_id,
        user_id=user_match.group(1) if user_match else None,
        article_id=article_id,
        record_kind=record_kind,
    )


def source_identity_key(url: str) -> tuple[object, ...]:
    identity = source_identity(url)
    if identity.has_record_id:
        return identity.origin, "record", identity.record_kind, identity.topic_id, identity.user_id, identity.article_id
    return identity.origin, "page", *_canonical_locator(url)


def same_source_identity(first_url: str, second_url: str) -> bool:
    """Compare the complete canonical source boundary, not just one matching component."""
    try:
        return source_identity_key(first_url) == source_identity_key(second_url)
    except SourceIdentityError:
        return first_url.strip() == second_url.strip()


def _require_matching_ids(expected: SourceIdentity, actual: SourceIdentity) -> None:
    if expected.record_kind is not None and actual.record_kind != expected.record_kind:
        raise SourceIdentityError(
            f"记录类型边界不匹配：{expected.record_kind} != {actual.record_kind}"
        )
    if expected.topic_id is not None and actual.topic_id != expected.topic_id:
        raise SourceIdentityError(f"topic ID 边界不匹配：{expected.topic_id} != {actual.topic_id}")
    if expected.user_id is not None and actual.user_id != expected.user_id:
        raise SourceIdentityError(f"用户 ID 边界不匹配：{expected.user_id} != {actual.user_id}")
    if expected.article_id is not None and actual.article_id != expected.article_id:
        raise SourceIdentityError(f"文章 ID 边界不匹配：{expected.article_id} != {actual.article_id}")


def validate_final_url(requested_url: str, final_url: str) -> SourceIdentity:
    expected = source_identity(requested_url)
    actual = source_identity(final_url)
    if actual.origin != expected.origin:
        raise SourceIdentityError(f"最终 URL 与请求 URL 不同源：{expected.origin} != {actual.origin}")
    expected_fragment = urlsplit(requested_url).fragment
    actual_fragment = urlsplit(final_url).fragment
    if expected_fragment and actual_fragment != expected_fragment:
        raise SourceIdentityError(
            f"最终 URL fragment 边界不匹配：{expected_fragment!r} != {actual_fragment!r}"
        )
    if expected.has_record_id:
        _require_matching_ids(expected, actual)
    elif _canonical_locator(requested_url) != _canonical_locator(final_url):
        raise SourceIdentityError(
            f"最终 URL 页面边界不匹配：{_canonical_locator(requested_url)!r} != {_canonical_locator(final_url)!r}"
        )
    return actual


def validate_related_url(
    page_url: str,
    related_url: str,
    *,
    require_matching_id: bool,
) -> SourceIdentity:
    page = source_identity(page_url)
    related = source_identity(related_url)
    if page.origin != related.origin:
        raise SourceIdentityError(f"相关来源与页面不同源：{page.origin} != {related.origin}")
    if require_matching_id:
        _require_matching_ids(page, related)
    return related


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _json_has_identity(value: object, keys: frozenset[str], expected: str) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _normalized_key(key) in keys and str(item) == expected:
                return True
            if _json_has_identity(item, keys, expected):
                return True
    elif isinstance(value, list):
        return any(_json_has_identity(item, keys, expected) for item in value)
    return False


def structured_body_matches_identity(body: str, identity: SourceIdentity) -> bool:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return False
    checks = (
        (identity.topic_id, frozenset({"topicid", "threadid"})),
        (identity.user_id, frozenset({"userid", "uid", "memberid", "authorid"})),
        (identity.article_id, frozenset({"articleid", "postid", "recordid"})),
    )
    return any(expected is not None and _json_has_identity(payload, keys, expected) for expected, keys in checks)


class _EmbeddedParser(HTMLParser):
    def __init__(
        self,
        base_url: str,
        *,
        content_only: bool = False,
        allowed_origins: Collection[str] = (),
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.content_only = content_only
        self.allowed_origins = frozenset(allowed_origins)
        self.resources: list[DiscoveredDocument] = []
        self.seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        document_type = {"iframe": DocumentType.IFRAME, "script": DocumentType.SCRIPT}.get(tag.lower())
        if document_type is None:
            return
        source = dict(attrs).get("src")
        if not source:
            return
        url = urljoin(self.base_url, source.strip())
        try:
            base = source_identity(self.base_url)
            related = source_identity(url)
            if related.origin != base.origin and related.origin not in self.allowed_origins:
                return
            if self.content_only and not _is_content_document(
                self.base_url,
                url,
                document_type,
            ):
                return
        except SourceIdentityError:
            return
        if url in self.seen:
            return
        self.seen.add(url)
        self.resources.append(DiscoveredDocument(url, document_type, len(self.resources)))


class _NamedTopicParser(HTMLParser):
    def __init__(self, base_url: str, anchor: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.anchor = anchor
        self.resources: list[DiscoveredDocument] = []
        self.seen: set[str] = set()
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        self._href = dict(attrs).get("href")
        self._parts.clear()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        href = self._href
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        self._href = None
        self._parts.clear()
        if self.anchor not in text:
            return
        url = urljoin(self.base_url, href.strip())
        try:
            identity = validate_related_url(self.base_url, url, require_matching_id=False)
        except SourceIdentityError:
            return
        if identity.topic_id is None or url in self.seen:
            return
        self.seen.add(url)
        self.resources.append(DiscoveredDocument(url, DocumentType.HTML, len(self.resources)))


def discover_embedded_documents(html: str, base_url: str) -> tuple[DiscoveredDocument, ...]:
    source_identity(base_url)
    parser = _EmbeddedParser(base_url)
    parser.feed(html)
    parser.close()
    return tuple(parser.resources)


def _is_content_document(base_url: str, url: str, document_type: DocumentType) -> bool:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if document_type is DocumentType.IFRAME:
        return path.startswith("/main/bbs/")
    if path.endswith(_NON_TEXT_ASSET_SUFFIXES):
        return False
    base_host = (urlsplit(base_url).hostname or "").lower()
    return (
        "/upload/script/" in path
        or "/upload/" in path
        or path.startswith("/htm/bbs/")
        or path.endswith("/view_content.php")
        or (base_host == "a.99818.vip" and path in {"/024s1x.aspx", "/jsq.aspx"})
    )


def discover_content_documents(
    html: str,
    base_url: str,
    *,
    allowed_origins: Collection[str] = (),
) -> tuple[DiscoveredDocument, ...]:
    source_identity(base_url)
    normalized_origins = frozenset(source_identity(url).origin for url in allowed_origins)
    parser = _EmbeddedParser(
        base_url,
        content_only=True,
        allowed_origins=normalized_origins,
    )
    normalized = html.replace("\\'", "'").replace('\\"', '"')
    parser.feed(normalized)
    parser.close()
    for source in _DYNAMIC_SCRIPT_SOURCE_PATTERN.findall(normalized):
        url = urljoin(base_url, source.strip())
        try:
            base = source_identity(base_url)
            related = source_identity(url)
            if related.origin != base.origin and related.origin not in normalized_origins:
                continue
        except SourceIdentityError:
            continue
        if url in parser.seen or not _is_content_document(base_url, url, DocumentType.SCRIPT):
            continue
        parser.seen.add(url)
        parser.resources.append(DiscoveredDocument(url, DocumentType.SCRIPT, len(parser.resources)))
    return tuple(parser.resources)


def discover_named_topic_documents(
    html: str,
    base_url: str,
    anchor: str,
) -> tuple[DiscoveredDocument, ...]:
    source_identity(base_url)
    if not anchor.strip():
        raise ValueError("topic 链接锚点不能为空")
    parser = _NamedTopicParser(base_url, anchor)
    parser.feed(html)
    parser.close()
    return tuple(parser.resources)


class _PeriodKeywordLinkParser(HTMLParser):
    def __init__(self, base_url: str, period: int, keyword: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.period_prefix = re.compile(rf"^\s*(?:第\s*)?0*{period}(?!\d)\s*期\s*[:：]")
        self.keyword = re.sub(r"\s+", " ", keyword).strip()
        self.article_urls: list[str] = []
        self.page_urls: list[str] = []
        self.has_target_period_article = False
        self.observed_periods: list[int] = []
        self._href: str | None = None
        self._parts: list[str] = []
        base = urlsplit(base_url)
        self._base_path = base.path.lower()
        self._base_list_id = parse_qs(base.query).get("id", ())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a" and self._href is None:
            self._href = dict(attrs).get("href")
            self._parts.clear()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        href = self._href
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        self._href = None
        self._parts.clear()
        url = urljoin(self.base_url, href.strip())
        try:
            validate_related_url(self.base_url, url, require_matching_id=False)
        except SourceIdentityError:
            return
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path.lower().endswith("/article.aspx"):
            article_ids = query.get("id", ())
            valid_article = len(article_ids) == 1 and article_ids[0].isdigit()
            observed = re.match(r"^\s*(?:第\s*)?0*(\d{1,4})\s*期", text)
            if valid_article and observed:
                self.observed_periods.append(int(observed.group(1)))
            if self.period_prefix.search(text) and valid_article:
                self.has_target_period_article = True
            if self.period_prefix.search(text) and self.keyword in text and valid_article:
                self.article_urls.append(url)
            return
        if parsed.path.lower() != self._base_path:
            return
        if query.get("id", ()) != self._base_list_id:
            return
        pages = query.get("page", ())
        if len(pages) == 1 and pages[0].isdigit():
            self.page_urls.append(url)


def discover_period_keyword_links(
    html: str,
    base_url: str,
    period: int,
    keyword: str,
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    source_identity(base_url)
    if not keyword.strip():
        raise ValueError("文章关键字不能为空")
    parser = _PeriodKeywordLinkParser(base_url, period, keyword)
    parser.feed(html)
    parser.close()
    return tuple(parser.article_urls), tuple(parser.page_urls), parser.has_target_period_article


def collect_embedded_documents(
    parent: SourceDocument,
    resources: Iterable[DiscoveredDocument],
    fetcher: Callable[[DiscoveredDocument], SourceDocument],
    *,
    max_documents: int = 20,
) -> SourceBundle:
    discovered = tuple(resources)
    if len(discovered) > max_documents:
        raise ValueError(f"嵌入文档数量超过上限 {max_documents}")
    documents = [parent]
    for resource in discovered:
        fetched = fetcher(resource)
        validate_related_url(parent.final_url, fetched.final_url, require_matching_id=False)
        if fetched.document_type is not resource.document_type:
            raise ValueError("嵌入文档类型与发现记录不一致")
        documents.append(
            SourceDocument(
                fetched.text,
                fetched.final_url,
                fetched.document_type,
                fetched.priority,
                fetched.source_id,
                len(documents),
                fetched.record_id,
            )
        )
    diagnostics = (
        f"embedded_discovered:{len(discovered)}",
        f"embedded_fetched:{len(documents) - 1}",
        "scan_complete:1",
    )
    return SourceBundle(documents, diagnostics, scan_complete=True)


def collect_content_documents(
    parent: SourceDocument,
    resources: Iterable[DiscoveredDocument],
    fetcher: Callable[[DiscoveredDocument], SourceDocument],
    *,
    max_depth: int = 3,
    max_documents: int = 64,
    allowed_origins: Collection[str] = (),
) -> SourceBundle:
    queue = [(resource, 0) for resource in resources]
    documents = [parent]
    seen = {resource.url for resource, _depth in queue}
    depth_truncated = False
    total_bytes = len(parent.text.encode("utf-8"))
    while queue and len(documents) - 1 < max_documents:
        resource, depth = queue.pop(0)
        fetched = fetcher(resource)
        validate_final_url(resource.url, fetched.final_url)
        total_bytes += len(fetched.text.encode("utf-8"))
        if total_bytes > 64_000_000:
            raise ValueError("站点内容文档累计超过 64000000 字节")
        if fetched.document_type is not resource.document_type:
            raise ValueError("内容文档类型与发现记录不一致")
        documents.append(
            SourceDocument(
                fetched.text,
                fetched.final_url,
                fetched.document_type,
                fetched.priority,
                fetched.source_id,
                len(documents),
                fetched.record_id,
            )
        )
        nested_resources = discover_content_documents(
            fetched.text,
            fetched.final_url,
            allowed_origins=allowed_origins,
        )
        if depth + 1 >= max_depth:
            depth_truncated = depth_truncated or any(nested.url not in seen for nested in nested_resources)
            continue
        for nested in nested_resources:
            if nested.url in seen:
                continue
            seen.add(nested.url)
            queue.append((nested, depth + 1))
    truncation_diagnostics = tuple(
        marker
        for truncated, marker in (
            (depth_truncated, "content_truncated:depth_limit"),
            (bool(queue), "content_truncated:document_limit"),
        )
        if truncated
    )
    diagnostics = (
        f"content_discovered:{len(seen)}",
        f"content_fetched:{len(documents) - 1}",
        *(truncation_diagnostics or ("scan_complete:1",)),
    )
    return SourceBundle(documents, diagnostics, scan_complete=not truncation_diagnostics)


def discover_period_page_links(html, base_url, period, keyword):
    source_identity(base_url)
    if not keyword.strip():
        raise ValueError("文章关键字不能为空")
    parser = _PeriodKeywordLinkParser(base_url, period, keyword)
    parser.feed(html)
    parser.close()
    return tuple(parser.article_urls), tuple(dict.fromkeys(parser.page_urls)), tuple(parser.observed_periods)
