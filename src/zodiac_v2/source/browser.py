from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Collection
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.source.documents import SourceIdentity, SourceIdentityError, source_identity, validate_final_url
from zodiac_v2.source.http import DEFAULT_MAX_BYTES, SourceFetchCode, SourceFetchError
from zodiac_v2.source.identity_records import IdentityRecordMissing, project_response_record

BROWSER_CONCURRENCY = 2
MAX_BROWSER_RESPONSES = 32
MAX_BROWSER_RESPONSE_BYTES = 16_000_000
MAX_BROWSER_TOTAL_BYTES = 32_000_000
_BROWSER_SLOTS = threading.BoundedSemaphore(BROWSER_CONCURRENCY)


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

    def __post_init__(self) -> None:
        object.__setattr__(self, 'responses', tuple(self.responses))


class BrowserRenderer(Protocol):
    def capture(self, url: str, *, timeout: float, allowed_response_urls: Collection[str] = (),
                allowed_response_origins: Collection[str] = ()) -> BrowserCapture: ...


class PlaywrightBrowserRenderer:
    def capture(self, url: str, *, timeout: float, allowed_response_urls: Collection[str] = (),
                allowed_response_origins: Collection[str] = ()) -> BrowserCapture:
        try:
            from importlib import import_module
            playwright_api = import_module("playwright.sync_api")
        except ImportError as exc:
            raise SourceFetchError(SourceFetchCode.BROWSER_UNAVAILABLE, 'Playwright 未安装', url=url) from exc
        sync_playwright = playwright_api.sync_playwright
        playwright_timeout = getattr(playwright_api, 'TimeoutError', TimeoutError)
        origins = {source_identity(item).origin for item in allowed_response_origins}
        deadline = monotonic() + timeout
        if not _BROWSER_SLOTS.acquire(timeout=max(0, timeout)):
            raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, '等待浏览器并发名额超时', url=url)
        captured = []
        errors = []
        total_bytes = 0
        exact_urls = frozenset(allowed_response_urls)

        def remaining_milliseconds():
            seconds = deadline - monotonic()
            if seconds <= 0:
                raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'浏览器取源总超时 {timeout:g}秒', url=url)
            return max(1, round(seconds * 1000))

        try:
            with sync_playwright() as playwright:
                # Sync Playwright objects stay in the thread that creates them.
                browser = playwright.chromium.launch(headless=True, timeout=remaining_milliseconds())
                try:
                    context = browser.new_context(service_workers='block')
                    context.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'font', 'media'} else route.continue_())
                    page = context.new_page()

                    def record_response(response):
                        nonlocal total_bytes
                        if errors:
                            return
                        try:
                            response_url = response.url
                            try:
                                response_origin = source_identity(response_url).origin
                            except SourceIdentityError:
                                return
                            if response_url not in exact_urls and response_origin not in origins:
                                return
                            content_type = response.header_value('content-type') or ''
                            if 'json' not in content_type.lower():
                                return
                            if not 200 <= response.status < 300:
                                if response_url in exact_urls:
                                    raise SourceFetchError(SourceFetchCode.HTTP_STATUS, f'目标浏览器接口 HTTP {response.status}', url=response_url, status=response.status)
                                return
                            if len(captured) >= MAX_BROWSER_RESPONSES:
                                raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口响应数量超过上限', url=response_url)
                            length = response.header_value('content-length')
                            if length and length.isdigit() and int(length) > min(MAX_BROWSER_RESPONSE_BYTES, MAX_BROWSER_TOTAL_BYTES - total_bytes):
                                raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口声明长度超过字节上限', url=response_url)
                            remaining_milliseconds()
                            body = response.text()
                            size = len(body.encode('utf-8'))
                            total_bytes += size
                            if size > MAX_BROWSER_RESPONSE_BYTES or total_bytes > MAX_BROWSER_TOTAL_BYTES:
                                raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口累计字节数超过上限', url=response_url)
                            remaining_milliseconds()
                            captured.append(BrowserResponse(response_url, response.status, content_type, body))
                        except SourceFetchError as exc:
                            errors.append(exc)
                        except Exception as exc:
                            errors.append(SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'读取目标浏览器响应失败：{exc}', url=url))

                    page.on('response', record_response)
                    response = page.goto(url, wait_until='domcontentloaded', timeout=remaining_milliseconds())
                    if response is not None and not 200 <= response.status < 300:
                        raise SourceFetchError(SourceFetchCode.HTTP_STATUS, f'浏览器页面 HTTP {response.status}', url=url, status=response.status)
                    # Polling/WebSocket pages may never become network-idle.  DOMContentLoaded
                    # is already proven; network-idle is only a bounded settle hint, not a
                    # correctness prerequisite.  A short final settle lets response handlers
                    # drain without turning a healthy polling page into a false network failure.
                    try:
                        page.wait_for_load_state('networkidle', timeout=min(3_000, remaining_milliseconds()))
                    except playwright_timeout:
                        settle = min(500, remaining_milliseconds())
                        if hasattr(page, 'wait_for_timeout'):
                            page.wait_for_timeout(settle)
                    if errors:
                        raise errors[0]
                    html = page.content()
                    remaining_milliseconds()
                    if len(html.encode('utf-8')) + total_bytes > MAX_BROWSER_TOTAL_BYTES:
                        raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器正文和接口累计字节数超过上限', url=url)
                    return BrowserCapture(page.url, html, tuple(captured))
                finally:
                    with suppress(Exception):
                        browser.close()
        except SourceFetchError:
            raise
        except Exception as exc:
            raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'浏览器取源失败：{exc}', url=url) from exc
        finally:
            _BROWSER_SLOTS.release()


def _response_matches_identity(response_url: str, body: str, expected: SourceIdentity) -> bool:
    try:
        related = source_identity(response_url)
        if related.origin != expected.origin:
            return False
        project_response_record(body, expected)
        return True
    except SourceIdentityError:
        return False


def browser_documents(renderer: BrowserRenderer, page_url: str, *, timeout: float = 20,
                      max_chars: int = DEFAULT_MAX_BYTES, allowed_response_urls: Collection[str] = (),
                      allowed_response_origins: Collection[str] = ()) -> SourceBundle:
    try:
        expected = source_identity(page_url)
        exact_urls = frozenset(allowed_response_urls)
        for response_url in exact_urls:
            source_identity(response_url)
        origins = {expected.origin}
        origins.update(source_identity(item).origin for item in allowed_response_origins)
        capture = renderer.capture(page_url, timeout=timeout, allowed_response_urls=exact_urls,
                                   allowed_response_origins=origins if expected.has_record_id else ())
        capture_identity = validate_final_url(page_url, capture.final_url)
        total_bytes = len(capture.html.encode('utf-8'))
        if total_bytes > max_chars:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, f'浏览器正文超过 {max_chars} 字节', url=page_url)
        if len(capture.responses) > MAX_BROWSER_RESPONSES:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口响应数量超过上限', url=page_url)
    except SourceFetchError:
        raise
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=page_url) from exc
    except Exception as exc:
        raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'浏览器取源失败：{exc}', url=page_url) from exc
    documents = [SourceDocument(capture.html, capture.final_url, DocumentType.BROWSER, 0,
                               f'browser-page:{capture.final_url}', 0,
                               capture_identity.topic_id or capture_identity.article_id)]
    accepted = rejected = 0
    seen = set()
    for response in capture.responses:
        try:
            related = source_identity(response.url)
        except SourceIdentityError:
            rejected += 1
            continue
        explicit = response.url in exact_urls
        eligible = (200 <= response.status < 300 and 'json' in response.content_type.lower()
                    and (explicit or expected.has_record_id and related.origin in origins))
        if not eligible:
            rejected += 1
            continue
        size = len(response.body.encode('utf-8'))
        total_bytes += size
        if size > max_chars or total_bytes > MAX_BROWSER_TOTAL_BYTES:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, f'浏览器接口响应超过 {max_chars} 字节或累计字节上限', url=response.url)
        try:
            if expected.has_record_id:
                body = project_response_record(response.body, expected)
            else:
                json.loads(response.body)
                body = response.body
        except IdentityRecordMissing as exc:
            if explicit:
                raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=response.url) from exc
            rejected += 1
            continue
        except (SourceIdentityError, ValueError) as exc:
            raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=response.url) from exc
        key = (response.url, body)
        if key in seen:
            rejected += 1
            continue
        seen.add(key)
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        documents.append(SourceDocument(body, response.url, DocumentType.JSON, 1,
                         f'browser-response:{response.url}:{digest}', len(documents),
                         expected.topic_id or expected.article_id))
        accepted += 1
    diagnostics = ('browser:200', f'accepted_responses:{accepted}', f'rejected_responses:{rejected}', 'scan_complete:1')
    return SourceBundle(documents, diagnostics, scan_complete=True)
