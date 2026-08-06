from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic
from typing import Protocol

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
)
from zodiac_v2.source.http import (
    EMBEDDED_MAX_BYTES,
    HttpTransport,
    SourceFetchCode,
    SourceFetchError,
    default_http_transport,
    fetch_http_document,
)
from zodiac_v2.validation.conflicts import validate_candidates

DEFAULT_SITE_TIMEOUT = 60.0
HTTP_CONSENSUS_ATTEMPTS = 5
HTTP_CONSENSUS_CONFIRMATIONS = 2
CACHE_SUCCESS_RATE_PERCENT = 85


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
        parent = fetch_http_document(self.transport, site.url, timeout=timeout, identity_url=site.url)
        return SourceBundle((parent,), ("http:200", "scan_complete:0"), scan_complete=False)

    def embedded(self, site: SiteConfig, bundle: SourceBundle, timeout: float) -> SourceBundle:
        if not bundle.documents:
            return SourceBundle(
                (),
                (*bundle.diagnostics, "embedded_discovered:0", "embedded_fetched:0", "scan_complete:1"),
                scan_complete=True,
            )
        parent = bundle.documents[0]
        resources = discover_content_documents(parent.text, parent.final_url)
        if not resources:
            return SourceBundle(
                bundle.documents,
                (*bundle.diagnostics, "embedded_discovered:0", "embedded_fetched:0", "scan_complete:1"),
                scan_complete=True,
            )
        deadline = monotonic() + timeout

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
                max_bytes=EMBEDDED_MAX_BYTES,
                document_type=resource.document_type,
                page_order=resource.page_order + 1,
            )
            _remaining_budget(deadline, timeout, site.url, "内容文档取源总超时")
            return document

        return collect_content_documents(parent, resources, fetch)

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
            (f"named-topic:200:{len(documents)}", "scan_complete:1"),
            scan_complete=True,
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
                    SourceFetchCode.SOURCE_IDENTITY,
                    "同栏目分页超过安全上限 10 页",
                    url=site.url,
                )
            article_urls, page_urls = discover_period_keyword_links(
                document.text,
                document.final_url,
                target_period,
                site.article_keyword,
            )
            matches.extend(article_urls)
            for page_url in page_urls:
                if page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                pending.append(
                    fetch_http_document(
                        self.transport,
                        page_url,
                        timeout=_remaining_budget(deadline, timeout, site.url, "栏目分页取源总超时"),
                        identity_url=page_url,
                        source_id=f"period-list:{page_url}",
                    )
                )
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
        return browser_documents(self.renderer, site.url, timeout=timeout, allowed_response_urls=allowed)

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


class ScrapeService:
    def __init__(self, gateway: SourceGateway, registry: BoundParser | ParserRegistry) -> None:
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
        )
        results: list[ScrapeResult] = []
        for period in selected_periods:
            extracted = self._evaluate(history_site, period, bundle, RunMode.READ_ONLY)
            if extracted.ok and extracted.candidate is not None:
                results.append(
                    ScrapeResult.success(
                        site,
                        period,
                        extracted.candidate,
                        extracted.documents,
                        writable=False,
                    )
                )
            else:
                results.append(
                    ScrapeResult.failure(
                        site,
                        period,
                        extracted.failure_code or FailureCode.OTHER,
                        extracted.reason,
                        extracted.documents,
                    )
                )
        return tuple(results)

    def _fetch(self, site: SiteConfig, timeout: float) -> SourceBundle:
        if site.source_policy == "api_then_http":
            return self.gateway.api_then_http(site, timeout)
        if site.source_policy == "browser_user":
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
            probes.append(
                (
                    self._evaluate(site, target_period, bundle, mode),
                    self._evaluate(site, target_period + 1, bundle, RunMode.READ_ONLY)
                    if target_period < 9999
                    else None,
                )
            )

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
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        deadline = monotonic() + timeout

        def remaining() -> float:
            return _remaining_budget(deadline, timeout, site.url, "站点总超时")

        documents = ()
        try:
            if site.source_policy == "http_consensus":
                return self._http_consensus(site, target_period, mode, remaining)
            try:
                bundle = self._fetch(site, remaining())
            except SourceFetchError:
                if site.source_policy != "http_then_browser":
                    raise
                bundle = self.gateway.browser(site, remaining())
            if site.source_policy == "http_period_keyword_article":
                bundle = self.gateway.period_keyword_article(site, bundle, target_period, remaining())
            if site.source_policy in {"api_then_http", "browser_user"}:
                bundle = bind_user_forum_target(site.url, bundle, target_period)
            documents = bundle.documents
            result = self._evaluate(site, target_period, bundle, mode)
            remaining()
            if site.source_policy in {"http_documents", "http_named_topic"}:
                if not result.ok and result.failure_code is not FailureCode.DEDICATED_PARSER_MISS:
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
            article_bundles = self.gateway.article_api(site, remaining())
            article_documents = tuple(
                document
                for article_bundle in article_bundles
                for document in article_bundle.documents
            )
            remaining()
            if article_documents:
                article_result = self._evaluate(
                    site,
                    target_period,
                    SourceBundle(
                        article_documents,
                        ("derived-api:combined", "scan_complete:1"),
                        scan_complete=True,
                    ),
                    mode,
                )
                remaining()
                if article_result.failure_code is not FailureCode.DEDICATED_PARSER_MISS:
                    return article_result
            browser_bundle = self.gateway.browser(site, remaining())
            remaining()
            browser_result = self._evaluate(site, target_period, browser_bundle, mode)
            remaining()
            return browser_result
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


def commit_formal_single(
    results: Iterable[ScrapeResult],
    *,
    cache_path: Path,
    paths: OutputPaths,
    permit: WritePermit,
) -> tuple[ScrapeResult, ...]:
    permit.require_formal_single(permit.target_period)
    materialized = tuple(results)
    for result in materialized:
        if result.target_period != permit.target_period:
            raise PermissionError("抓取结果期数与正式单期写入许可不一致")
        if result.ok and not result.writable:
            raise PermissionError("抓取结果未获得正式单期写入资格")
        if result.ok and result.candidate is not None:
            if not result.validator_issued:
                raise PermissionError("抓取结果未由统一验证器签发")
            expected_receipt = build_validation_receipt(
                result.site,
                result.target_period,
                result.candidate,
                result.documents,
            )
            if result.validation_receipt != expected_receipt:
                raise PermissionError("抓取结果缺少有效统一验证回执")
    final_tuple = tuple(materialized)
    write_output_payloads(build_output_payloads(final_tuple, paths), permit)

    successful_results = tuple(result for result in final_tuple if result.ok)
    if not successful_results:
        return final_tuple
    if len(successful_results) * 100 <= len(final_tuple) * CACHE_SUCCESS_RATE_PERCENT:
        print(
            f"成功率 {len(successful_results)}/{len(final_tuple)} 未超过 "
            f"{CACHE_SUCCESS_RATE_PERCENT}%，缓存不更新",
            flush=True,
        )
        return final_tuple

    try:
        updated_cache, quarantined_errors = load_recent_cache_for_commit(cache_path)
    except ValueError as exc:
        _report_cache_issue(f"缓存读取失败：{exc}")
        return final_tuple

    accepted_count = 0
    for result in successful_results:
        quarantined_reason = quarantined_errors.get(result.site.identity)
        if quarantined_reason is not None:
            _report_cache_issue(f"{result.site.name} 缓存目录已隔离：{quarantined_reason}")
            continue
        try:
            record = cache_record_from_result(result)
            updated_cache = update_recent_cache(
                updated_cache,
                (record,),
                current_period=permit.target_period,
                permit=permit,
            )
        except ValueError as exc:
            _report_cache_issue(f"{result.site.name}：{exc}")
            continue
        accepted_count += 1

    if not accepted_count:
        return final_tuple
    failed_sites = tuple(
        (
            result.site.identity,
            result.reason or f"{result.target_period}期抓取失败",
        )
        for result in final_tuple
        if not result.ok
    )
    if failed_sites:
        try:
            updated_cache = mark_failed_sites(
                updated_cache,
                failed_sites,
                current_period=permit.target_period,
                permit=permit,
            )
        except ValueError as exc:
            _report_cache_issue(f"失败站点状态标记未完成：{exc}")
            return final_tuple
    try:
        write_recent_cache(cache_path, updated_cache, permit)
    except (OSError, ValueError) as exc:
        _report_cache_issue(f"缓存写入失败：{exc}")
    return final_tuple
