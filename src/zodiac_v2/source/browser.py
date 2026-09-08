from __future__ import annotations

import asyncio
from collections.abc import Collection
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from zodiac_v2.contracts import DocumentType, SourceBundle, SourceDocument
from zodiac_v2.source.documents import (
    SourceIdentity,
    SourceIdentityError,
    source_identity,
    structured_body_matches_identity,
    validate_final_url,
)
from zodiac_v2.source.http import DEFAULT_MAX_BYTES, SourceFetchCode, SourceFetchError


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
    def capture(
        self,
        url: str,
        *,
        timeout: float,
        allowed_response_urls: Collection[str] = (),
        allowed_response_origins: Collection[str] = (),
    ) -> BrowserCapture:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SourceFetchError(
                SourceFetchCode.BROWSER_UNAVAILABLE,
                "Playwright 未安装",
                url=url,
            ) from exc

        captured: list[BrowserResponse] = []
        deadline = monotonic() + timeout
        exact_response_urls = frozenset(allowed_response_urls)
        response_origins = frozenset(allowed_response_origins)

        def remaining_milliseconds() -> int:
            seconds = deadline - monotonic()
            if seconds <= 0:
                raise SourceFetchError(
                    SourceFetchCode.BROWSER_CAPTURE,
                    f"浏览器取源总超时 {timeout:g}秒",
                    url=url,
                )
            return max(1, round(seconds * 1000))

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    timeout=remaining_milliseconds(),
                )
                page = browser.new_page()

                def record_response(response: object) -> None:
                    try:
                        response_url = response.url  # type: ignore[attr-defined]
                        response_identity = source_identity(response_url)
                        if response_url not in exact_response_urls and response_identity.origin not in response_origins:
                            return
                        content_type = response.header_value("content-type") or ""  # type: ignore[attr-defined]
                        if "json" not in content_type.lower():
                            return
                        captured.append(
                            BrowserResponse(
                                response_url,
                                int(response.status),  # type: ignore[attr-defined]
                                content_type,
                                response.text(),  # type: ignore[attr-defined]
                            )
                        )
                    except (Exception, asyncio.CancelledError):
                        return

                page.on("response", record_response)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=remaining_milliseconds())
                    with suppress(Exception):
                        page.wait_for_load_state("networkidle", timeout=remaining_milliseconds())
                    return BrowserCapture(page.url, page.content(), tuple(captured))
                finally:
                    with suppress(Exception):
                        page.remove_listener("response", record_response)
                    browser.close()
        except SourceFetchError:
            raise
        except Exception as exc:
            raise SourceFetchError(
                SourceFetchCode.BROWSER_CAPTURE,
                f"浏览器取源失败：{exc}",
                url=url,
            ) from exc


def _response_matches_identity(response_url: str, body: str, expected: SourceIdentity) -> bool:
    related = source_identity(response_url)
    pairs = (
        (expected.topic_id, related.topic_id),
        (expected.user_id, related.user_id),
        (expected.article_id, related.article_id),
    )
    for wanted, actual in pairs:
        if wanted is not None and actual is not None:
            return wanted == actual
    return structured_body_matches_identity(body, expected)


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
        capture = renderer.capture(
            page_url,
            timeout=timeout,
            allowed_response_urls=exact_response_urls,
            allowed_response_origins=allowed_origins,
        )
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
    for response in capture.responses:
        key = (response.url, response.body)
        try:
            response_identity = source_identity(response.url)
        except SourceIdentityError:
            rejected += 1
            continue
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
        if expected.has_record_id and not _response_matches_identity(
            response.url,
            response.body,
            expected,
        ):
            rejected += 1
            continue
        accepted += 1
        documents.append(
            SourceDocument(
                response.body,
                response.url,
                DocumentType.JSON,
                1,
                f"browser-response:{response.url}",
                len(documents),
                response_identity.topic_id or response_identity.article_id,
            )
        )
    diagnostics = (
        "browser:200",
        f"accepted_responses:{accepted}",
        f"rejected_responses:{rejected}",
        "scan_complete:1",
    )
    return SourceBundle(documents, diagnostics, scan_complete=True)
