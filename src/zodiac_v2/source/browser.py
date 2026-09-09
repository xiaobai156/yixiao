from __future__ import annotations

import base64
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
_BROWSER_READ_CHUNK = 64 * 1024
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


def _header_value(headers: Collection[dict[str, object]], name: str) -> str:
    lowered = name.lower()
    for header in headers:
        if str(header.get('name', '')).lower() == lowered:
            return str(header.get('value', ''))
    return ''


def _fulfill_headers(headers: Collection[dict[str, object]], payload_size: int) -> list[dict[str, str]]:
    blocked = {'content-length', 'content-encoding', 'transfer-encoding'}
    result = [
        {'name': str(header.get('name', '')), 'value': str(header.get('value', ''))}
        for header in headers
        if str(header.get('name', '')).lower() not in blocked
    ]
    result.append({'name': 'Content-Length', 'value': str(payload_size)})
    return result


def _decode_json_payload(payload: bytes, url: str) -> str:
    try:
        return payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise SourceFetchError(SourceFetchCode.DECODE, '浏览器 JSON 响应不是有效 UTF-8', url=url) from exc


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
        captured: list[BrowserResponse] = []
        errors: list[SourceFetchError] = []
        total_bytes = 0
        exact_urls = frozenset(allowed_response_urls)

        def remaining_milliseconds() -> int:
            seconds = deadline - monotonic()
            if seconds <= 0:
                raise SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'浏览器取源总超时 {timeout:g}秒', url=url)
            return max(1, round(seconds * 1000))

        def is_eligible(response_url: str) -> bool:
            if response_url in exact_urls:
                return True
            try:
                return source_identity(response_url).origin in origins
            except SourceIdentityError:
                return False

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, timeout=remaining_milliseconds())
                try:
                    context = browser.new_context(service_workers='block')
                    context.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'font', 'media'} else route.continue_())
                    page = context.new_page()
                    if (exact_urls or origins) and not hasattr(context, 'new_cdp_session'):
                        def record_response(response):
                            nonlocal total_bytes
                            if errors:
                                return
                            try:
                                response_url = response.url
                                if not is_eligible(response_url):
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
                                length = response.header_value('content-length') or ''
                                remaining = min(MAX_BROWSER_RESPONSE_BYTES, MAX_BROWSER_TOTAL_BYTES - total_bytes)
                                if remaining <= 0 or length.isdigit() and int(length) > remaining:
                                    raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口声明长度超过字节上限', url=response_url)
                                body = response.text()
                                size = len(body.encode('utf-8'))
                                if size > MAX_BROWSER_RESPONSE_BYTES or total_bytes + size > MAX_BROWSER_TOTAL_BYTES:
                                    raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口累计字节数超过上限', url=response_url)
                                total_bytes += size
                                captured.append(BrowserResponse(response_url, response.status, content_type, body))
                            except SourceFetchError as exc:
                                errors.append(exc)
                            except Exception as exc:
                                errors.append(SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'读取目标浏览器响应失败：{exc}', url=url))

                        page.on('response', record_response)
                    elif exact_urls or origins:
                        cdp = context.new_cdp_session(page)
    
                        def continue_response(request_id: str) -> None:
                            cdp.send('Fetch.continueResponse', {'requestId': request_id})
    
                        def fail_response(request_id: str) -> None:
                            with suppress(Exception):
                                cdp.send('Fetch.failRequest', {'requestId': request_id, 'errorReason': 'Aborted'})
    
                        def record_paused(params: dict[str, object]) -> None:
                            nonlocal total_bytes
                            request_id = str(params.get('requestId', ''))
                            request = params.get('request')
                            if not request_id or not isinstance(request, dict) or 'responseStatusCode' not in params:
                                if request_id:
                                    with suppress(Exception):
                                        cdp.send('Fetch.continueRequest', {'requestId': request_id})
                                return
                            response_url = str(request.get('url', ''))
                            headers_value = params.get('responseHeaders')
                            headers = headers_value if isinstance(headers_value, list) else []
                            content_type = _header_value(headers, 'content-type')
                            explicit = response_url in exact_urls
                            status = int(params.get('responseStatusCode', 0) or 0)
                            if not is_eligible(response_url) or 'json' not in content_type.lower():
                                continue_response(request_id)
                                return
                            if not 200 <= status < 300:
                                if explicit:
                                    errors.append(SourceFetchError(SourceFetchCode.HTTP_STATUS, f'目标浏览器接口 HTTP {status}', url=response_url, status=status))
                                continue_response(request_id)
                                return
                            if len(captured) >= MAX_BROWSER_RESPONSES:
                                errors.append(SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口响应数量超过上限', url=response_url))
                                fail_response(request_id)
                                return
                            length = _header_value(headers, 'content-length')
                            remaining = min(MAX_BROWSER_RESPONSE_BYTES, MAX_BROWSER_TOTAL_BYTES - total_bytes)
                            if remaining <= 0 or length.isdigit() and int(length) > remaining:
                                errors.append(SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口声明长度超过字节上限', url=response_url))
                                fail_response(request_id)
                                return
                            handle = None
                            chunks: list[bytes] = []
                            response_size = 0
                            try:
                                handle = str(cdp.send('Fetch.takeResponseBodyAsStream', {'requestId': request_id})['stream'])
                                while True:
                                    remaining_milliseconds()
                                    part = cdp.send('IO.read', {'handle': handle, 'size': _BROWSER_READ_CHUNK})
                                    raw = str(part.get('data', ''))
                                    chunk = base64.b64decode(raw) if part.get('base64Encoded') else raw.encode('utf-8')
                                    response_size += len(chunk)
                                    if response_size > MAX_BROWSER_RESPONSE_BYTES or total_bytes + response_size > MAX_BROWSER_TOTAL_BYTES:
                                        raise SourceFetchError(SourceFetchCode.TOO_LARGE, '浏览器接口流式正文超过字节上限', url=response_url)
                                    chunks.append(chunk)
                                    if part.get('eof'):
                                        break
                                payload = b''.join(chunks)
                                body = _decode_json_payload(payload, response_url)
                                total_bytes += len(payload)
                                captured.append(BrowserResponse(response_url, status, content_type, body))
                                cdp.send('Fetch.fulfillRequest', {
                                    'requestId': request_id,
                                    'responseCode': status,
                                    'responseHeaders': _fulfill_headers(headers, len(payload)),
                                    'body': base64.b64encode(payload).decode('ascii'),
                                })
                            except SourceFetchError as exc:
                                errors.append(exc)
                                fail_response(request_id)
                            except Exception as exc:
                                errors.append(SourceFetchError(SourceFetchCode.BROWSER_CAPTURE, f'流式读取目标浏览器响应失败：{exc}', url=response_url or url))
                                fail_response(request_id)
                            finally:
                                if handle is not None:
                                    with suppress(Exception):
                                        cdp.send('IO.close', {'handle': handle})
    
                        cdp.on('Fetch.requestPaused', record_paused)
                        cdp.send('Fetch.enable', {'patterns': [{'urlPattern': '*', 'requestStage': 'Response'}]})
                    response = page.goto(url, wait_until='domcontentloaded', timeout=remaining_milliseconds())
                    if response is not None and not 200 <= response.status < 300:
                        raise SourceFetchError(SourceFetchCode.HTTP_STATUS, f'浏览器页面 HTTP {response.status}', url=url, status=response.status)
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
