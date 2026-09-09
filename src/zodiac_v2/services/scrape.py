from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from time import monotonic
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

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
    build_validation_receipt,
)
from zodiac_v2.services.formal import (
    commit_formal_single as commit_formal_single,
    commit_full_formal_single as commit_full_formal_single,
    commit_targeted_formal_single as commit_targeted_formal_single,
)
from zodiac_v2.parsers.common import decoded_script_fragments
from zodiac_v2.parsers.registry import ParserRegistry
from zodiac_v2.source.api import bind_user_forum_target, derived_article_api_urls, fetch_api_then_page
from zodiac_v2.source.browser import BrowserRenderer, PlaywrightBrowserRenderer, browser_documents
from zodiac_v2.source.documents import (
    collect_content_documents,
    discover_content_documents,
    discover_named_topic_documents,
    discover_period_keyword_page,
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

    def close(self) -> None:
        close = getattr(self.renderer, "close", None)
        if callable(close):
            close()

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

    def period_keyword_article(
        self,
        site: SiteConfig,
        bundle: SourceBundle,
        target_period: int,
        timeout: float,
    ) -> SourceBundle:
        if site.article_keyword is None:
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                f"站点 {site.name} 缺少文章关键字",
                url=site.url,
            )
        deadline = monotonic() + timeout
        pending = list(bundle.documents)
        seen_pages = {document.final_url for document in pending}
        matches: list[str] = []
        scanned = 0
        while pending:
            document = pending.pop(0)
            scanned += 1
            if scanned > 10:
                raise SourceFetchError(
                    SourceFetchCode.SOURCE_IDENTITY, "同栏目分页超过安全上限 10 页", url=site.url,
                )
            article_urls, page_urls, observed_periods = discover_period_keyword_page(
                document.text, document.final_url, target_period, site.article_keyword,
            )
            matches.extend(article_urls)
            # The configured period-list strategy scans descending lists. A
            # newer first page must not stop a search for an older target page.
            if observed_periods and max(observed_periods) < target_period:
                continue
            current_page = int(parse_qs(urlsplit(document.final_url).query).get("page", ["1"])[0])
            forward = sorted(
                (int(parse_qs(urlsplit(url).query)["page"][0]), url)
                for url in set(page_urls)
                if url not in seen_pages
                and int(parse_qs(urlsplit(url).query)["page"][0]) > current_page
            )
            if not forward:
                continue
            page_number, page_url = forward[0]
            if page_number != current_page + 1:
                raise SourceFetchError(
                    SourceFetchCode.SOURCE_IDENTITY,
                    f"同栏目分页缺少连续下一页 {current_page + 1}，无法完成唯一性扫描", url=site.url,
                )
            if scanned + len(pending) >= 10:
                raise SourceFetchError(
                    SourceFetchCode.SOURCE_IDENTITY, "同栏目分页超过安全上限 10 页", url=site.url,
                )
            seen_pages.add(page_url)
            pending.append(fetch_http_document(
                self.transport, page_url,
                timeout=_remaining_budget(deadline, timeout, site.url, "栏目分页取源总超时"),
                identity_url=page_url, source_id=f"period-list:{page_url}",
            ))
        unique_matches = tuple(dict.fromkeys(matches))
        if len(unique_matches) != 1:
            raise SourceFetchError(
                SourceFetchCode.SOURCE_IDENTITY,
                f"{target_period}期完整关键字 {site.article_keyword!r} 详情链接命中 {len(unique_matches)} 个",
                url=site.url,
            )
        detail_url = unique_matches[0]
        detail = fetch_http_document(
            self.transport,
            detail_url,
            timeout=_remaining_budget(deadline, timeout, site.url, "文章详情取源总超时"),
            identity_url=detail_url,
            source_id=f"ttss-article:{detail_url}",
        )
        return SourceBundle(
            (detail,),
            (f"period-list-pages:{scanned}", "period-keyword-match:1", "scan_complete:1"),
            scan_complete=True,
        )

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

    def close(self) -> None:
        close = getattr(self.gateway, "close", None)
        if callable(close):
            close()

    def _evaluate(
        self,
        site: SiteConfig,
        target_period: int,
        bundle: SourceBundle,
        mode: RunMode,
    ) -> ScrapeResult:
        try:
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

    def _http_consensus(
        self,
        site: SiteConfig,
        target_period: int,
        mode: RunMode,
        remaining: Callable[[], float],
    ) -> ScrapeResult:
        probes: list[tuple[ScrapeResult, ScrapeResult | None]] = []
        fetch_failures: list[ScrapeResult] = []
        target_observations = []

        for _attempt in range(HTTP_CONSENSUS_ATTEMPTS):
            try:
                bundle = self.gateway.http(site, remaining())
                bundle = self.gateway.embedded(site, bundle, remaining())
                remaining()
            except SourceFetchError as exc:
                fetch_failures.append(
                    ScrapeResult.failure(
                        site,
                        target_period,
                        _failure_code(exc),
                        str(exc),
                        (),
                    )
                )
                continue
            # Presence and edge validation are different questions. Inspect the
            # active cycle for explicit conflicts even when a period is not on
            # its required edge; two later confirmations cannot erase a conflict.
            try:
                candidates = tuple(self.registry.parse(site, bundle))
            except Exception as exc:
                fetch_failures.append(ScrapeResult.failure(
                    site, target_period, FailureCode.DEDICATED_PARSER_MISS,
                    f"专属解析异常：{type(exc).__name__}: {exc}", bundle.documents,
                ))
                continue
            current_presence = validate_period_presence(site, bundle, candidates, target_period)
            next_presence = (
                validate_period_presence(site, bundle, candidates, target_period + 1)
                if target_period < 9999 else None
            )
            for observation in (current_presence, next_presence):
                if observation is not None and observation.failure_code is FailureCode.CONFLICT:
                    return ScrapeResult.failure(
                        site, target_period, FailureCode.CONFLICT,
                        f"共识取源发现明确冲突，禁止被确认次数掩盖：{observation.reason}", bundle.documents,
                    )
            if current_presence.ok:
                target_observations.append(current_presence.candidate.zodiac)
            if len(set(target_observations)) > 1:
                return ScrapeResult.failure(
                    site, target_period, FailureCode.CONFLICT,
                    f"{target_period}期多次取源结果冲突：{sorted(set(target_observations))}", bundle.documents,
                )
            next_result = None
            if next_presence is not None and next_presence.ok:
                next_result = ScrapeResult.success(
                    site, target_period + 1, next_presence.candidate, bundle.documents, writable=False,
                )
            target_result = self._evaluate(site, target_period, bundle, mode)
            if target_result.failure_code is FailureCode.CONFLICT:
                return ScrapeResult.failure(
                    site, target_period, FailureCode.CONFLICT,
                    f"共识取源的最终验证发现明确冲突：{target_result.reason}", bundle.documents,
                )
            probes.append((target_result, next_result))
            remaining()

        newer_hits = tuple(
            next_result
            for _, next_result in probes
            if next_result is not None and next_result.ok
        )
        newer_values = {
            result.candidate.zodiac
            for result in newer_hits
            if result.candidate is not None
        }
        if len(newer_values) > 1:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.CONFLICT,
                f"多次取源的 {target_period + 1}期结果冲突：{sorted(newer_values)}",
                newer_hits[0].documents,
            )
        if newer_hits:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.DIRECTION,
                f"多次取源发现更新的 {target_period + 1}期有效结果"
                f"[{next(iter(newer_values))}]，指定 {target_period}期不是{site.direction.value}边界",
                newer_hits[0].documents,
            )

        target_hits = tuple(target_result for target_result, _ in probes if target_result.ok)
        target_values = {
            result.candidate.zodiac
            for result in target_hits
            if result.candidate is not None
        }
        if len(target_values) > 1:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.CONFLICT,
                f"{target_period}期多次取源结果冲突：{sorted(target_values)}",
                target_hits[0].documents,
            )
        if len(target_hits) >= HTTP_CONSENSUS_CONFIRMATIONS:
            return target_hits[0]
        if target_hits:
            return ScrapeResult.failure(
                site,
                target_period,
                FailureCode.SOURCE_IDENTITY,
                f"{target_period}期多次取源仅有 {len(target_hits)} 次有效确认，"
                f"少于 {HTTP_CONSENSUS_CONFIRMATIONS} 次",
                target_hits[0].documents,
            )
        if probes:
            representative = probes[-1][0]
            return ScrapeResult.failure(
                site,
                target_period,
                representative.failure_code or FailureCode.SOURCE_IDENTITY,
                f"{target_period}期多次取源均未确认；最后结果：{representative.reason}",
                representative.documents,
            )
        if fetch_failures:
            return fetch_failures[-1]
        return ScrapeResult.failure(
            site,
            target_period,
            FailureCode.SOURCE_IDENTITY,
            f"{target_period}期多次取源未取得有效文档",
            (),
        )

    def scrape_site(
        self,
        site: SiteConfig,
        target_period: int,
        mode: RunMode = RunMode.READ_ONLY,
        *,
        timeout: float = DEFAULT_SITE_TIMEOUT,
    ) -> ScrapeResult:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是有限正数")
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
                    if not page_bundle.scan_complete:
                        page_bundle = self.gateway.embedded(site, page_bundle, remaining())
                    documents = page_bundle.documents
                    remaining()
                    if not page_bundle.scan_complete or not _bundle_is_empty_shell(page_bundle):
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


