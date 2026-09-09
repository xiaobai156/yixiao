from __future__ import annotations

import asyncio
import hashlib
import math
import threading
from collections.abc import Collection
from concurrent.futures import Future, TimeoutError as FutureTimeout
from queue import Queue
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.source.documents import (
    SourceIdentity,
    SourceIdentityError,
    source_identity,
    validate_final_url,
)
from zodiac_v2.source.http import DEFAULT_MAX_BYTES, SourceFetchCode, SourceFetchError
from zodiac_v2.source.projection import project_response

BROWSER_CONCURRENCY = 2
MAX_BROWSER_RESPONSES = 32
MAX_BROWSER_TOTAL_BYTES = 32_000_000


@dataclass(frozen=True, slots=True)
class BrowserResponse:
    url: str
    status: int
    content_type: str
    body: str


@dataclass(frozen=True, slots=True)
class BrowserCapture:
    final_url: str
    html: str
    responses: tuple[BrowserResponse, ...]
    scan_complete: bool = True
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "responses", tuple(self.responses))


class BrowserRenderer(Protocol):
    def capture(
        self,
        url: str,
        *,
        timeout: float,
        allowed_response_urls: Collection[str] = (),
        allowed_response_origins: Collection[str] = (),
    ) -> BrowserCapture: ...


class PlaywrightBrowserRenderer:
    """Two owning threads reuse browsers; each capture gets an isolated context.

    Sync Playwright objects never cross thread boundaries. close() sends one
    sentinel to each owner and joins it; a later batch can open a new pool.
    """
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._queue = None
        self._workers: tuple[threading.Thread, ...] = ()

    def capture(
        self, url: str, *, timeout: float,
        allowed_response_urls: Collection[str] = (),
        allowed_response_origins: Collection[str] = (),
    ) -> BrowserCapture:
        return self.capture_bounded(
            url, timeout=timeout, max_bytes=DEFAULT_MAX_BYTES,
            allowed_response_urls=allowed_response_urls,
            allowed_response_origins=allowed_response_origins,
        )

    def capture_bounded(
        self, url: str, *, timeout: float, max_bytes: int,
        allowed_response_urls: Collection[str] = (),
        allowed_response_origins: Collection[str] = (),
    ) -> BrowserCapture:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("浏览器 timeout 必须是有限正数")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("浏览器响应上限必须是正整数")
        future: Future[BrowserCapture] = Future()
        job = (future, url, monotonic() + timeout, timeout, min(max_bytes, MAX_BROWSER_TOTAL_BYTES),
               frozenset(allowed_response_urls), frozenset(allowed_response_origins))
        with self._guard:
            if not self._workers:
                queue: Queue = Queue()
                self._queue = queue
                self._workers = tuple(
                    threading.Thread(target=self._worker, args=(queue,), name=f"zodiac-browser-{i}", daemon=True)
                    for i in range(BROWSER_CONCURRENCY)
                )
                for worker in self._workers:
                    worker.start()
            self._queue.put(job)
        try:
            return future.result(timeout=timeout + 1)
        except FutureTimeout as exc:
            future.cancel()
            raise SourceFetchError(
                SourceFetchCode.BROWSER_CAPTURE, f"浏览器排队或取源总超时 {timeout:g}秒", url=url,
            ) from exc

    def close(self) -> None:
        with self._guard:
            if not self._workers:
                return
            for _worker in self._workers:
                self._queue.put(None)
            for worker in self._workers:
                worker.join()
            self._workers = ()
            self._queue = None

    def _worker(self, queue: Queue) -> None:
        playwright = None
        browser = None
        try:
            while True:
                job = queue.get()
                if job is None:
                    return
                future, url, deadline, timeout, max_bytes, exact_urls, origins = job
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if monotonic() >= deadline:
                        raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, "浏览器排队已耗尽站点预算", url=url)
                    try:
                        from playwright.sync_api import sync_playwright
                    except ImportError as exc:
                        raise SourceFetchError(SourceFetchCode.BROWSER_UNAVAILABLE, "Playwright 未安装", url=url) from exc
                    if playwright is None:
                        playwright = sync_playwright().start()
                    if browser is None or not browser.is_connected():
                        browser = playwright.chromium.launch(
                            headless=True, timeout=max(1, int((deadline - monotonic()) * 1000)),
                        )
                    future.set_result(self._capture_page(browser, url, deadline, timeout, max_bytes, exact_urls, origins))
                except SourceFetchError as exc:
                    future.set_exception(exc)
                except (Exception, asyncio.CancelledError) as exc:
                    future.set_exception(SourceFetchError(
                        SourceFetchCode.BROWSER_CAPTURE, f"浏览器取源失败：{exc}", url=url,
                    ))
        finally:
            if browser is not None:
                with suppress(Exception):
                    browser.close()
            if playwright is not None:
                with suppress(Exception):
                    playwright.stop()

    def _capture_page(self, browser, url, deadline, timeout, max_bytes, exact_urls, origins) -> BrowserCapture:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        def remaining_ms() -> int:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f"浏览器取源总超时 {timeout:g}秒", url=url)
            return max(1, int(remaining * 1000))

        captured: list[BrowserResponse] = []
        pending: dict[object, object] = {}
        completed: set[str] = set()
        errors: list[SourceFetchError] = []
        received = 0
        total_bytes = 0
        context = browser.new_context(service_workers="block")
        page = None

        def record_response(response) -> None:
            nonlocal received
            try:
                response_url = response.url
                identity = source_identity(response_url)
                if response_url not in exact_urls and identity.origin not in origins:
                    return
                if not 200 <= response.status < 300:
                    if response_url in exact_urls:
                        errors.append(SourceFetchError(SourceFetchCode.HTTP_STATUS,
                                      f"浏览器目标接口 HTTP {response.status}", url=response_url, status=response.status))
                    return
                if "json" not in (response.header_value("content-type") or "").lower():
                    if response_url in exact_urls:
                        errors.append(SourceFetchError(SourceFetchCode.SOURCE_IDENTITY,
                                      "浏览器目标接口未返回 JSON", url=response_url))
                    return
                received += 1
                length = response.header_value("content-length")
                if received > MAX_BROWSER_RESPONSES or (length is not None and int(length) > max_bytes):
                    errors.append(SourceFetchError(SourceFetchCode.TOO_LARGE, "浏览器接口数量或声明字节数超限", url=response_url))
                    return
                pending[response.request] = response
            except SourceIdentityError:
                # Non-HTTP assets (for example data: URLs) are never API sources.
                return
            except (Exception, asyncio.CancelledError) as exc:
                errors.append(SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f"接口响应头读取失败：{exc}", url=url))

        def record_finished(request) -> None:
            nonlocal total_bytes
            response = pending.pop(request, None)
            if response is None or errors:
                return
            try:
                # requestfinished means the body is ready; never block the
                # response-header callback waiting for an unfinished body.
                body = response.text()
                size = len(body.encode("utf-8"))
                total_bytes += size
                if size > max_bytes or total_bytes > MAX_BROWSER_TOTAL_BYTES:
                    raise SourceFetchError(SourceFetchCode.TOO_LARGE, "浏览器接口实际或累计字节数超限", url=response.url)
                remaining_ms()
                captured.append(BrowserResponse(response.url, response.status,
                                                response.header_value("content-type") or "", body))
                completed.add(response.url)
            except SourceFetchError as exc:
                errors.append(exc)
            except (Exception, asyncio.CancelledError) as exc:
                errors.append(SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f"目标接口正文读取失败：{exc}", url=url))

        def record_failed(request) -> None:
            if request in pending or request.url in exact_urls:
                errors.append(SourceFetchError(SourceFetchCode.NETWORK, "浏览器目标接口请求失败", url=request.url))
                pending.pop(request, None)

        def route_resource(route) -> None:
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        try:
            context.route("**/*", route_resource)
            page = context.new_page()
            page.on("response", record_response)
            page.on("requestfinished", record_finished)
            page.on("requestfailed", record_failed)
            response = page.goto(url, wait_until="domcontentloaded", timeout=remaining_ms())
            if response is not None and not 200 <= response.status < 300:
                raise SourceFetchError(SourceFetchCode.HTTP_STATUS, f"浏览器页面 HTTP {response.status}",
                                       url=url, status=response.status)
            if errors:
                raise errors[0]
            idle = True
            try:
                for target_url in exact_urls:
                    if target_url not in completed:
                        page.wait_for_event(
                            "requestfinished", predicate=lambda request, target=target_url: request.url == target,
                            timeout=remaining_ms(),
                        )
                    if errors:
                        raise errors[0]
                idle_timeout = min(2_000, remaining_ms()) if exact_urls else remaining_ms()
                page.wait_for_load_state("networkidle", timeout=idle_timeout)
            except PlaywrightTimeout:
                idle = False
            if errors:
                raise errors[0]
            remaining_ms()
            html = page.content()
            if len(html.encode("utf-8")) > max_bytes or len(html.encode("utf-8")) + total_bytes > MAX_BROWSER_TOTAL_BYTES:
                raise SourceFetchError(SourceFetchCode.TOO_LARGE, "浏览器正文或累计字节数超限", url=url)
            complete = not pending and (idle or (bool(exact_urls) and exact_urls <= completed))
            return BrowserCapture(page.url, html, tuple(captured), complete,
                                  () if complete else ("browser:pending-source",))
        finally:
            if page is not None:
                for event, handler in (("response", record_response), ("requestfinished", record_finished),
                                       ("requestfailed", record_failed)):
                    with suppress(Exception):
                        page.remove_listener(event, handler)
            with suppress(Exception):
                context.close()

def _response_matches_identity(response_url: str, body: str, expected: SourceIdentity) -> bool:
    return project_response(body, expected, response_url) is not None


def browser_documents(
    renderer: BrowserRenderer,
    page_url: str,
    *,
    timeout: float = 20,
    max_chars: int = DEFAULT_MAX_BYTES,
    allowed_response_urls: Collection[str] = (),
    allowed_response_origins: Collection[str] = (),
) -> SourceBundle:
    try:
        expected = source_identity(page_url)
        exact_response_urls = frozenset(allowed_response_urls)
        for response_url in exact_response_urls:
            source_identity(response_url)
        allowed_origins = {expected.origin}
        allowed_origins.update(source_identity(url).origin for url in allowed_response_origins)
        capture_options = dict(
            timeout=timeout, allowed_response_urls=exact_response_urls, allowed_response_origins=allowed_origins,
        )
        if isinstance(renderer, PlaywrightBrowserRenderer):
            capture = renderer.capture_bounded(page_url, max_bytes=max_chars, **capture_options)
        else:
            capture = renderer.capture(page_url, **capture_options)
        capture_identity = validate_final_url(page_url, capture.final_url)
        if len(capture.html.encode("utf-8")) > max_chars:
            raise SourceFetchError(
                SourceFetchCode.TOO_LARGE,
                f"浏览器正文超过 {max_chars} 字节",
                url=page_url,
            )
    except SourceFetchError:
        raise
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=page_url) from exc
    except Exception as exc:
        raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f"浏览器取源失败：{exc}", url=page_url) from exc

    documents = [
        SourceDocument(
            capture.html,
            capture.final_url,
            DocumentType.BROWSER,
            0,
            f"browser-page:{capture.final_url}",
            0,
            capture_identity.topic_id or capture_identity.article_id,
        )
    ]
    accepted = 0
    rejected = 0
    seen: set[tuple[str, str]] = set()
    total_bytes = len(capture.html.encode("utf-8"))
    if len(capture.responses) > MAX_BROWSER_RESPONSES:
        raise SourceFetchError(SourceFetchCode.TOO_LARGE, "浏览器接口响应数量超限", url=page_url)
    for response in capture.responses:
        total_bytes += len(response.body.encode("utf-8"))
        if total_bytes > MAX_BROWSER_TOTAL_BYTES:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, "浏览器累计响应字节数超限", url=page_url)
        key = (response.url, response.body)
        try:
            response_identity = source_identity(response.url)
        except SourceIdentityError:
            rejected += 1
            continue
        if response.url in exact_response_urls and not 200 <= response.status < 300:
            raise SourceFetchError(SourceFetchCode.HTTP_STATUS, f"浏览器目标接口 HTTP {response.status}",
                                   url=response.url, status=response.status)
        if response.url in exact_response_urls and "json" not in response.content_type.lower():
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "浏览器目标接口未返回 JSON", url=response.url)
        eligible = (
            key not in seen
            and 200 <= response.status < 300
            and "json" in response.content_type.lower()
            and (response.url in exact_response_urls or response_identity.origin in allowed_origins)
        )
        seen.add(key)
        if not eligible:
            rejected += 1
            continue
        if len(response.body.encode("utf-8")) > max_chars:
            raise SourceFetchError(
                SourceFetchCode.TOO_LARGE,
                f"浏览器接口响应超过 {max_chars} 字节",
                url=response.url,
            )
        if not expected.has_record_id and response.url not in exact_response_urls:
            rejected += 1
            continue
        try:
            projected = project_response(response.body, expected, response.url)
        except SourceIdentityError as exc:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=response.url) from exc
        if projected is None:
            if response.url in exact_response_urls:
                raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, "目标接口未找到唯一可信目标记录", url=response.url)
            rejected += 1
            continue
        accepted += 1
        digest = hashlib.sha256(projected.encode("utf-8")).hexdigest()[:16]
        documents.append(
            SourceDocument(
                projected,
                response.url,
                DocumentType.JSON,
                1,
                f"browser-response:{accepted}:{response.url}:{digest}",
                len(documents),
                expected.topic_id or expected.article_id,
            )
        )
    diagnostics = (
        "browser:200",
        f"accepted_responses:{accepted}",
        f"rejected_responses:{rejected}",
        *capture.diagnostics,
        f"scan_complete:{int(capture.scan_complete)}",
    )
    return SourceBundle(documents, diagnostics, scan_complete=capture.scan_complete)
