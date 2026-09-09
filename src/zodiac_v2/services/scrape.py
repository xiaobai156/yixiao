from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path
from time import monotonic
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from zodiac_v2.cache import (
    load_recent_cache_for_commit,
    mark_failed_sites,
    update_recent_cache,
    write_recent_cache,
)
from zodiac_v2.contracts import (
    CacheRecord,
    Direction,
    DocumentType,
    FailureCode,
    RunMode,
    ScrapeResult,
    SiteConfig,
    SourceBundle,
    SourceDocument,
    WritePermit,
    build_validation_receipt,
)
from zodiac_v2.output import OutputPaths, build_output_payloads, write_output_payloads
from zodiac_v2.parsers.common import decoded_script_fragments
from zodiac_v2.parsers.registry import ParserRegistry
from zodiac_v2.source.api import bind_user_forum_target, derived_article_api_urls, fetch_api_then_page
from zodiac_v2.source.browser import BrowserRenderer, PlaywrightBrowserRenderer, browser_documents
from zodiac_v2.source.documents import (
    collect_content_documents,
    discover_content_documents,
    discover_named_topic_documents,
    discover_period_keyword_links,
    discover_period_page_links,
    source_identity,
)
from zodiac_v2.source.http import (
    DEFAULT_MAX_BYTES,
    EMBEDDED_MAX_BYTES,
    HttpTransport,
    SourceFetchCode,
    SourceFetchError,
    default_http_transport,
    fetch_http_document,
)
from zodiac_v2.validation.conflicts import _active_candidates, validate_candidates, validate_period_presence

DEFAULT_SITE_TIMEOUT = 60.0
HTTP_CONSENSUS_ATTEMPTS = 5
HTTP_CONSENSUS_CONFIRMATIONS = 2
CACHE_SUCCESS_RATE_PERCENT = 85
CONTENT_CDN_ORIGINS = tuple(
    f"https://xia{index:02}.cosds.{domain}"
    for domain in ("ahsccn.com", "aohjifv.com")
    for index in range(1, 7)
)


class SourceGateway(Protocol):
    def http(self, site: SiteConfig, timeout: float) -> SourceBundle: ...

    def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle: ...

    def named_topic(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle: ...

    def period_keyword_article(
        self, site: SiteConfig, bundle: SourceBundle, target_period: int, timeout: float
    ) -> SourceBundle: ...

    def api_then_http(self, site: SiteConfig, timeout: float) -> SourceBundle: ...

    def browser(self, site: SiteConfig, timeout: float) -> SourceBundle: ...

    def article_api(self, site: SiteConfig, timeout: float) -> tuple[SourceBundle, ...]: ...


class BoundParser(Protocol):
    def parse(self, site: SiteConfig, bundle: SourceBundle): ...


def _remaining_budget(deadline: float, total: float, url: str, label: str) -> float:
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise SourceFetchError(
            SourceFetchCode.NETWORK,
            f"{label} {total:g}秒",
            url=url,
        )
    return seconds


class DefaultSourceGateway:
    def __init__(
        self,
        transport: HttpTransport | None = None,
        renderer: BrowserRenderer | None = None,
    ) -> None:
        self.transport = transport or default_http_transport()
        self.renderer = renderer or PlaywrightBrowserRenderer()

    def http(self, site: SiteConfig, timeout: float) -> SourceBundle:
        configured_url = urlsplit(site.url)
        network_url = configured_url._replace(fragment="").geturl()
        parent = fetch_http_document(
            self.transport,
            network_url,
            timeout=timeout,
            identity_url=network_url,
        )
        if configured_url.fragment:
            document_url = urlsplit(parent.final_url)._replace(fragment=configured_url.fragment).geturl()
            parent = SourceDocument(
                parent.text,
                document_url,
                parent.document_type,
                parent.priority,
                parent.source_id,
                parent.page_order,
                configured_url.fragment,
            )
        return SourceBundle((parent,), ("http:200", "scan_complete:0"), scan_complete=False)

    def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
        if not bundle.documents:
            return SourceBundle(
                (),
                (*bundle.diagnostics, "embedded_discovered:0", "embedded_fetched:0", "scan_complete:1"),
                scan_complete=True,
            )
        parent = bundle.documents[0]
        resources = discover_content_documents(
            parent.text,
            parent.final_url,
            allowed_origins=CONTENT_CDN_ORIGINS,
        )
        if not resources:
            return SourceBundle(
                bundle.documents,
                (*bundle.diagnostics, "embedded_discovered:0", "embedded_fetched:0", "scan_complete:1"),
                scan_complete=True,
            )
        deadline = monotonic() + timeout
        max_bytes = site.embedded_max_bytes or EMBEDDED_MAX_BYTES

        def fetch(resource):
            document = fetch_http_document(
                self.transport,
                resource.url,
                timeout=_remaining_budget(
                    deadline,
                    timeout,
                    site.url,
                    "内容文档取源总超时",
                ),
                max_bytes=max_bytes,
                document_type=resource.document_type,
                page_order=resource.page_order + 1,
            )
            _remaining_budget(deadline, timeout, site.url, "内容文档取源总超时")
            return document

        return collect_content_documents(
            parent,
            resources,
            fetch,
            allowed_origins=CONTENT_CDN_ORIGINS,
        )

    def named_topic(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
        resources = []
        seen: set[str] = set()
        for document in bundle.documents:
            for source in (document.text, *decoded_script_fragments(document.text)):
                for resource in discover_named_topic_documents(source, site.url, site.name):
                    if resource.url in seen:
                        continue
                    seen.add(resource.url)
                    resources.append(resource)
        if not resources:
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                f"未找到站名 {site.name} 对应的同源 topic 详情链接",
                url=site.url,
            )
        deadline = monotonic() + timeout
        documents = []
        scan_complete = True
        truncation_diagnostics: list[str] = []
        for resource in resources:
            detail = fetch_http_document(
                self.transport,
                resource.url,
                timeout=_remaining_budget(deadline, timeout, site.url, "topic 详情取源总超时"),
                identity_url=resource.url,
                document_type=resource.document_type,
                source_id=f"named-topic:{resource.url}",
                page_order=resource.page_order,
            )
            remaining = _remaining_budget(deadline, timeout, site.url, "topic 详情取源总超时")
            enriched = self.embedded(
                site,
                SourceBundle((detail,), ("named-topic:200", "scan_complete:0"), scan_complete=False),
                remaining,
            )
            scan_complete = scan_complete and enriched.scan_complete
            truncation_diagnostics.extend(
                diagnostic
                for diagnostic in enriched.diagnostics
                if diagnostic.startswith("content_truncated:")
            )
            documents.extend(
                SourceDocument(
                    item.text,
                    item.final_url,
                    item.document_type,
                    item.priority,
                    item.source_id,
                    len(documents),
                    item.record_id,
                )
                for item in enriched.documents
            )
        return SourceBundle(
            tuple(documents),
            (
                f"named-topic:200:{len(documents)}",
                *tuple(dict.fromkeys(truncation_diagnostics)),
                f"scan_complete:{int(scan_complete)}",
            ),
            scan_complete=scan_complete,
        )

    def period_keyword_article(self, site, bundle, target_period, timeout):
        if not site.article_keyword:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "缺少文章关键字", url=site.url)
        if len(bundle.documents) != 1:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "栏目分页必须从唯一入口开始", url=site.url)
        deadline = monotonic() + timeout
        document = bundle.documents[0]
        seen_pages = set()
        matches = []
        scanned = 0
        while True:
            if document.final_url in seen_pages:
                raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "栏目分页循环", url=site.url)
            seen_pages.add(document.final_url)
            scanned += 1
            article_urls, page_urls, periods = discover_period_page_links(document.text, document.final_url, target_period, site.article_keyword)
            matches.extend(article_urls)
            # Configured newest-first lists stop after a page of strictly older articles.
            if periods and max(periods) < target_period:
                break
            current_page = int(parse_qs(urlsplit(document.final_url).query).get("page", ["1"])[0])
            following = sorted({url for url in page_urls if int(parse_qs(urlsplit(url).query)["page"][0]) == current_page + 1})
            if not following:
                if page_urls and any(int(parse_qs(urlsplit(url).query)["page"][0]) > current_page for url in page_urls):
                    raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "缺少连续下一页，不能证明扫描完整", url=site.url)
                break
            if len(following) != 1 or scanned >= 10:
                raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "同栏目分页不唯一或超过安全上限 10 页", url=site.url)
            document = fetch_http_document(self.transport, following[0],
                timeout=_remaining_budget(deadline, timeout, site.url, "栏目分页取源总超时"),
                identity_url=following[0], source_id=f"period-list:{following[0]}")
        unique = tuple(dict.fromkeys(matches))
        if len(unique) != 1:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, f"{target_period}期完整关键字 {site.article_keyword!r} 详情链接命中 {len(unique)} 个", url=site.url)
        detail = fetch_http_document(self.transport, unique[0], timeout=_remaining_budget(deadline, timeout, site.url, "文章详情取源总超时"), identity_url=unique[0], source_id=f"ttss-article:{unique[0]}")
        return self.embedded(site, SourceBundle((detail,), (f"period-list-pages:{scanned}", "period-keyword-match:1"), scan_complete=False), _remaining_budget(deadline, timeout, site.url, "文章详情取源总超时"))

    def api_then_http(self, site: SiteConfig, timeout: float) -> SourceBundle:
        if site.api_url is None:
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                f"站点 {site.name} 的 api_then_http 策略缺少 api_url",
                url=site.url,
            )
        return fetch_api_then_page(
            self.transport,
            api_url=site.api_url,
            page_url=site.url,
            timeout=timeout,
        )

    def browser(self, site: SiteConfig, timeout: float) -> SourceBundle:
        allowed = (site.api_url,) if site.api_url else ()
        return browser_documents(
            self.renderer,
            site.url,
            timeout=timeout,
            max_chars=site.embedded_max_bytes or DEFAULT_MAX_BYTES,
            allowed_response_urls=allowed,
        )

    def article_api(self, site: SiteConfig, timeout: float) -> tuple[SourceBundle, ...]:
        urls = derived_article_api_urls(site.url)
        bundles: list[SourceBundle] = []
        deadline = monotonic() + timeout
        for api_url in urls:
            try:
                document = fetch_http_document(
                    self.transport,
                    api_url,
                    timeout=_remaining_budget(
                        deadline,
                        timeout,
                        site.url,
                        "文章 API 取源总超时",
                    ),
                    identity_url=site.url,
                    document_type=DocumentType.JSON,
                    source_id=f"api:{api_url.rsplit('/', 1)[-1]}",
                )
            except SourceFetchError as exc:
                if exc.code is SourceFetchCode.HTTP_STATUS and exc.status == 404:
                    _remaining_budget(deadline, timeout, site.url, "文章 API 取源总超时")
                    continue
                raise
            _remaining_budget(deadline, timeout, site.url, "文章 API 取源总超时")
            bundles.append(
                SourceBundle(
                    (document,),
                    ("derived-api:200", "scan_complete:1"),
                    scan_complete=True,
                )
            )
        return tuple(bundles)


def _failure_code(error: SourceFetchError) -> FailureCode:
    if error.code is SourceFetchCode.SOURCE_IDENTITY:
        return FailureCode.SOURCE_IDENTITY
    if error.code in {SourceFetchCode.TOO_LARGE, SourceFetchCode.DECODE}:
        return FailureCode.BOUNDARY
    return FailureCode.NETWORK


def _bundle_is_empty_shell(bundle: SourceBundle) -> bool:
    if not bundle.documents:
        return True
    for document in bundle.documents:
        if document.document_type is DocumentType.JSON:
            try:
                payload = json.loads(document.text)
            except json.JSONDecodeError:
                return False
            if payload not in (None, {}, []):
                return False
            continue
        without_code = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", document.text)
        visible = unescape(re.sub(r"(?s)<[^>]+>", " ", without_code))
        if visible.strip():
            return False
    return True


def _article_api_bundle(
    site: SiteConfig,
    documents: tuple[SourceDocument, ...],
) -> SourceBundle | None:
    expected_id = source_identity(site.url).article_id
    if expected_id is None:
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            "动态文章 URL 缺少文章 ID",
            url=site.url,
        )
    canonical_records: dict[str, tuple[dict[str, object], SourceDocument]] = {}
    for document in documents:
        try:
            payload = json.loads(document.text)
        except json.JSONDecodeError as exc:
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                "文章 API 返回非可信 JSON，禁止浏览器兜底",
                url=site.url,
            ) from exc
        if payload in (None, {}, []):
            continue
        rows = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(row, dict) for row in rows):
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                "文章 API 记录容器非法，禁止浏览器兜底",
                url=site.url,
            )
        for row in rows:
            raw_id = row.get("id")
            if (
                isinstance(raw_id, bool)
                or not isinstance(raw_id, (str, int))
                or not str(raw_id).strip()
            ):
                raise SourceFetchError(
                    SourceFetchCode.SOURCE_IDENTITY,
                    f"文章 API 非空记录缺少合法 ID（来源 {document.source_id}），禁止浏览器兜底",
                    url=site.url,
                )
            if str(raw_id).strip() != expected_id:
                raise SourceFetchError(
                    SourceFetchCode.SOURCE_IDENTITY,
                    f"文章 API 返回错误文章 ID {str(raw_id).strip()}，预期 {expected_id}"
                    f"（来源 {document.source_id}），禁止浏览器兜底",
                    url=site.url,
                )
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            canonical_records.setdefault(canonical, (row, document))
    if not canonical_records:
        return None
    if len(canonical_records) != 1:
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"文章 API 的 URL 文章 ID {expected_id} 出现冲突记录，禁止浏览器兜底",
            url=site.url,
        )
    record, source_document = next(iter(canonical_records.values()))
    body_fields = tuple(record.get(field) for field in ("content", "body", "html", "text") if field in record)
    if any(value is not None and not isinstance(value, str) for value in body_fields):
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"文章 API 的 URL 文章 ID {expected_id} 正文字段非法，禁止浏览器兜底",
            url=site.url,
        )
    if any(isinstance(value, str) and value.strip() for value in body_fields):
        selected_document = SourceDocument(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
            source_document.final_url,
            DocumentType.JSON,
            source_document.priority,
            source_document.source_id,
            0,
            expected_id,
        )
        return SourceBundle(
            (selected_document,),
            ("derived-api:unique-target", "scan_complete:1"),
            scan_complete=True,
        )
    if body_fields:
        return None
    raise SourceFetchError(
        SourceFetchCode.SOURCE_IDENTITY,
        f"文章 API 的 URL 文章 ID {expected_id} 正文字段非法，禁止浏览器兜底",
        url=site.url,
    )


class ScrapeService:
    def __init__(
        self,
        gateway: SourceGateway,
        registry: BoundParser | ParserRegistry,
    ) -> None:
        self.gateway = gateway
        self.registry = registry

    def _evaluate(
        self,
        site: SiteConfig,
        target_period: int,
        bundle: SourceBundle,
        mode: RunMode,
    ) -> ScrapeResult:
        try:
            if sum(len(document.text.encode("utf-8")) for document in bundle.documents) > 64_000_000:
                return ScrapeResult.failure(site, target_period, FailureCode.BOUNDARY, "站点文档累计超过 64000000 字节", bundle.documents)
            candidates = tuple(self.registry.parse(site, bundle))
        except Exception as exc:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.DEDICATED_PARSER_MISS,
                f"专属解析异常：{type(exc).__name__}: {exc}",
                bundle.documents,
            )
        if not candidates:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.DEDICATED_PARSER_MISS,
                f"专属解析未命中指定 {target_period}期，禁止回落通用解析",
                bundle.documents,
            )
        decision = validate_candidates(site, bundle, candidates, target_period)
        if not decision.ok or decision.candidate is None:
            return ScrapeResult.failure(
                site,
                target_period,
                decision.failure_code or FailureCode.OTHER,
                decision.reason,
                bundle.documents,
            )
        if mode is RunMode.FORMAL_SINGLE:
            return ScrapeResult._validated_success(
                site,
                target_period,
                decision.candidate,
                bundle.documents,
            )
        return ScrapeResult.success(
            site,
            target_period,
            decision.candidate,
            bundle.documents,
            writable=False,
        )

    def historical_results(
        self,
        site: SiteConfig,
        periods: Iterable[int],
        live_result: ScrapeResult,
    ) -> tuple[ScrapeResult, ...]:
        """Extract read-only history from the already direction-validated live document."""
        selected_periods = tuple(periods)
        if not live_result.ok or live_result.site.identity != site.identity:
            raise ValueError("历史提取必须基于同一站点已通过的实时方向结果")
        bundle = SourceBundle(
            live_result.documents,
            ("onboard-history:live-source", "scan_complete:1"),
            scan_complete=True,
        )
        history_site = SiteConfig(
            site.name,
            site.url,
            Direction.LEFT,
            site.section,
            site.parser_id,
            site.source_policy,
            site.api_url,
            site.article_keyword,
            site.embedded_max_bytes,
        )
        candidates = _active_candidates(
            tuple(self.registry.parse(history_site, bundle)),
            site.direction,
        )
        results: list[ScrapeResult] = []
        for period in selected_periods:
            decision = validate_candidates(history_site, bundle, candidates, period)
            if decision.ok and decision.candidate is not None:
                results.append(
                    ScrapeResult.success(
                        site,
                        period,
                        decision.candidate,
                        bundle.documents,
                        writable=False,
                    )
                )
            else:
                results.append(
                    ScrapeResult.failure(
                        site,
                        period,
                        decision.failure_code or FailureCode.OTHER,
                        decision.reason,
                        bundle.documents,
                    )
                )
        return tuple(results)

    def _fetch(self, site: SiteConfig, timeout: float) -> SourceBundle:
        if site.source_policy == "api_then_http":
            return self.gateway.api_then_http(site, timeout)
        if site.source_policy == "browser_user":
            return self.gateway.browser(site, timeout)
        if site.source_policy == "browser":
            return self.gateway.browser(site, timeout)
        if site.source_policy == "http_then_browser" and urlsplit(site.url).fragment:
            return self.gateway.browser(site, timeout)
        if site.source_policy in {
            "http_documents",
            "http_named_topic",
            "http_period_keyword_article",
            "http_then_browser",
        }:
            return self.gateway.http(site, timeout)
        raise SourceFetchError(
            SourceFetchCode.SOURCE_IDENTITY,
            f"未知取源策略：{site.source_policy}",
            url=site.url,
        )

    def _http_consensus(self, site, target_period, mode, remaining):
        hits = []
        last_failure = None
        newer_values = set()
        newer_documents = ()
        for _attempt in range(HTTP_CONSENSUS_ATTEMPTS):
            try:
                bundle = self.gateway.http(site, remaining())
                bundle = self.gateway.embedded(site, bundle, remaining())
                remaining()
            except SourceFetchError as exc:
                failure = ScrapeResult.failure(site, target_period, _failure_code(exc), str(exc), ())
                if exc.code is not SourceFetchCode.NETWORK and exc.code is not SourceFetchCode.HTTP_STATUS:
                    return failure
                last_failure = failure
                continue
            result = self._evaluate(site, target_period, bundle, mode)
            if result.failure_code is FailureCode.CONFLICT:
                return result
            try:
                candidates = tuple(self.registry.parse(site, bundle))
            except Exception:
                last_failure = result
                continue
            for period in (target_period, target_period + 1):
                if period > 9999:
                    continue
                presence = validate_period_presence(site, bundle, candidates, period)
                if presence.failure_code is FailureCode.CONFLICT:
                    return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT,
                        f"共识取源发现 {period}期明确冲突：{presence.reason}", bundle.documents)
                if presence.failure_code not in (None, FailureCode.PERIOD):
                    return ScrapeResult.failure(site, target_period, presence.failure_code, presence.reason, bundle.documents)
                if period > target_period and presence.ok:
                    newer_values.add(presence.candidate.zodiac)
                    newer_documents = bundle.documents
            if result.ok:
                hits.append(result)
            else:
                last_failure = result
        if len(newer_values) > 1:
            return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT, "多次取源的下一期结果冲突", newer_documents)
        if newer_values:
            return ScrapeResult.failure(site, target_period, FailureCode.DIRECTION,
                f"多次取源发现更新的 {target_period + 1}期有效结果，指定期不是方向边界", newer_documents)
        values = {result.candidate.zodiac for result in hits}
        if len(values) > 1:
            return ScrapeResult.failure(site, target_period, FailureCode.CONFLICT, f"目标期多次取源结果冲突：{sorted(values)}", hits[0].documents)
        if len(hits) >= HTTP_CONSENSUS_CONFIRMATIONS:
            return hits[0]
        if hits:
            return ScrapeResult.failure(site, target_period, FailureCode.SOURCE_IDENTITY, "多次取源有效确认不足", hits[0].documents)
        return last_failure or ScrapeResult.failure(site, target_period, FailureCode.SOURCE_IDENTITY, "多次取源未取得有效文档", ())

    def scrape_site(
        self,
        site: SiteConfig,
        target_period: int,
        mode: RunMode = RunMode.READ_ONLY,
        *,
        timeout: float = DEFAULT_SITE_TIMEOUT,
    ) -> ScrapeResult:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        deadline = monotonic() + timeout

        def remaining() -> float:
            return _remaining_budget(deadline, timeout, site.url, "站点总超时")

        documents = ()
        try:
            if site.source_policy == "http_consensus":
                return self._http_consensus(site, target_period, mode, remaining)
            article_urls = derived_article_api_urls(site.url)
            if site.source_policy == "http_then_browser" and article_urls:
                article_bundles = self.gateway.article_api(site, remaining())
                article_documents = tuple(
                    document
                    for article_bundle in article_bundles
                    for document in article_bundle.documents
                )
                documents = article_documents
                remaining()
                target_bundle = _article_api_bundle(site, article_documents) if article_documents else None
                if target_bundle is not None:
                    documents = target_bundle.documents
                    result = self._evaluate(site, target_period, target_bundle, mode)
                    remaining()
                    return result
                if not article_documents:
                    page_bundle = self.gateway.http(site, remaining())
                    page_bundle = self.gateway.embedded(site, page_bundle, remaining())
                    documents = page_bundle.documents
                    if not _bundle_is_empty_shell(page_bundle):
                        return self._evaluate(site, target_period, page_bundle, mode)
                browser_bundle = self.gateway.browser(site, remaining())
                documents = browser_bundle.documents
                remaining()
                result = self._evaluate(site, target_period, browser_bundle, mode)
                remaining()
                return result
            bundle = self._fetch(site, remaining())
            if site.source_policy == "http_period_keyword_article":
                bundle = self.gateway.period_keyword_article(site, bundle, target_period, remaining())
            if (
                site.source_policy == "api_then_http"
                and article_urls
                and "api:200" in bundle.diagnostics
            ):
                target_bundle = _article_api_bundle(site, bundle.documents)
                if target_bundle is None:
                    raise SourceFetchError(
                        SourceFetchCode.SOURCE_IDENTITY,
                        "文章 API 唯一目标记录正文为空，当前策略不允许浏览器兜底",
                        url=site.url,
                )
                bundle = target_bundle
            if site.source_policy == "http_then_browser" and not bundle.scan_complete:
                bundle = self.gateway.embedded(site, bundle, remaining())
                remaining()
            if site.source_policy in {"api_then_http", "browser_user"}:
                selector = getattr(self.registry, "select_source", None)
                selected_bundle = (
                    selector(site, bundle, target_period)
                    if callable(selector)
                    else None
                )
                bundle = (
                    selected_bundle
                    if selected_bundle is not None
                    else bind_user_forum_target(site.url, bundle, target_period)
                )
            documents = bundle.documents
            result = self._evaluate(site, target_period, bundle, mode)
            remaining()
            if site.source_policy in {"http_documents", "http_named_topic"}:
                if (
                    bundle.scan_complete
                    and not result.ok
                    and result.failure_code is not FailureCode.DEDICATED_PARSER_MISS
                ):
                    return result
                embedded_bundle = self.gateway.embedded(site, bundle, remaining())
                remaining()
                embedded_result = (
                    result
                    if embedded_bundle is bundle
                    else self._evaluate(site, target_period, embedded_bundle, mode)
                )
                remaining()
                if embedded_result.ok:
                    return embedded_result
                if embedded_result.failure_code is not FailureCode.DEDICATED_PARSER_MISS:
                    return embedded_result
                if site.source_policy == "http_documents":
                    return embedded_result
                named_bundle = self.gateway.named_topic(site, embedded_bundle, remaining())
                remaining()
                named_result = self._evaluate(site, target_period, named_bundle, mode)
                remaining()
                return named_result
            if not result.ok and result.failure_code is not FailureCode.DEDICATED_PARSER_MISS:
                return result
            if result.ok:
                return result
            if site.source_policy != "http_then_browser":
                return result
            if urlsplit(site.url).fragment:
                return result
            if _bundle_is_empty_shell(bundle):
                browser_bundle = self.gateway.browser(site, remaining())
                remaining()
                return self._evaluate(site, target_period, browser_bundle, mode)
            return result
        except SourceFetchError as exc:
            return ScrapeResult.failure(
                site,
                target_period,
                _failure_code(exc),
                str(exc),
                documents,
            )
        except Exception as exc:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.OTHER,
                f"{type(exc).__name__}: {exc}",
                documents,
            )

    def scrape_sites(
        self,
        sites: Iterable[SiteConfig],
        target_period: int,
        mode: RunMode = RunMode.READ_ONLY,
        *,
        timeout: float = DEFAULT_SITE_TIMEOUT,
        workers: int = 1,
        on_result: Callable[[int, int, ScrapeResult], None] | None = None,
    ) -> tuple[ScrapeResult, ...]:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
            raise ValueError("workers 必须是正整数")
        selected = tuple(sites)
        results: list[ScrapeResult | None] = [None] * len(selected)
        total = len(selected)
        completed = 0
        def record(index: int, result: ScrapeResult) -> None:
            nonlocal completed
            results[index] = result
            completed += 1
            if on_result is not None:
                on_result(completed, total, result)

        def run_batch(indices: tuple[int, ...]) -> None:
            if not indices:
                return
            if workers == 1:
                for index in indices:
                    record(
                        index,
                        self.scrape_site(selected[index], target_period, mode, timeout=timeout),
                    )
                return
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self.scrape_site,
                        selected[index],
                        target_period,
                        mode,
                        timeout=timeout,
                    ): index
                    for index in indices
                }
                for future in as_completed(futures):
                    record(futures[future], future.result())

        run_batch(tuple(range(len(selected))))
        return tuple(result for result in results if result is not None)


def cache_record_from_result(result: ScrapeResult) -> CacheRecord:
    if not result.ok or result.candidate is None:
        raise ValueError("失败结果不能转换为缓存记录")
    document = next(
        (item for item in result.documents if item.source_id == result.candidate.document_id),
        None,
    )
    if document is None:
        raise ValueError("候选来源文档不存在，禁止写入缓存")
    validation_receipt = result.validation_receipt or build_validation_receipt(
        result.site,
        result.target_period,
        result.candidate,
        result.documents,
    )
    return CacheRecord(
        result.site.name,
        result.site.url,
        result.site.direction,
        result.site.section,
        result.target_period,
        result.candidate.zodiac,
        document.source_id,
        document.final_url,
        hashlib.sha256(validation_receipt.encode("ascii")).hexdigest(),
        result.candidate.record_id,
    )


def _report_cache_issue(reason: str) -> None:
    print(f"缓存更新未完成（仅影响新增站点判重，不影响本轮抓取结果）：{reason}", flush=True)


def commit_formal_single(results, *, cache_path, paths, permit, expected_sites=None, existing_success_extra_names=()):
    """Compatibility name for a full batch; scope must be explicitly supplied."""
    from zodiac_v2.services.persistence import commit_full_formal_single
    if expected_sites is None:
        raise ValueError("全量正式提交必须提供 expected_sites，禁止子集覆盖")
    return commit_full_formal_single(results, expected_sites=expected_sites, cache_path=cache_path, paths=paths,
        permit=permit, existing_success_extra_names=existing_success_extra_names)
