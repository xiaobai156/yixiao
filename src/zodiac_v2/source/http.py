from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass
from http.client import IncompleteRead
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests

from zodiac_v2.contracts import DocumentType, SourceDocument, StrEnum
from zodiac_v2.source.documents import SourceIdentityError, source_identity, validate_final_url

DEFAULT_MAX_BYTES = 5_000_000
# Embedded script bundles can contain the site's historical archive in one
# response.  Keep the normal page limit unchanged, but allow a bounded larger
# limit for those explicitly discovered content documents.
EMBEDDED_MAX_BYTES = 8_000_000
DEFAULT_INSECURE_TLS_HOSTS: frozenset[str] = frozenset()
TRANSIENT_HTTP_STATUSES = frozenset({500, 502, 503, 504})


class SourceFetchCode(StrEnum):
    NETWORK = "network"
    HTTP_STATUS = "http_status"
    TOO_LARGE = "too_large"
    DECODE = "decode"
    SOURCE_IDENTITY = "source_identity"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    BROWSER_CAPTURE = "browser_capture"


class SourceFetchError(RuntimeError):
    def __init__(
        self,
        code: SourceFetchCode,
        message: str,
        *,
        url: str,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.url = url
        self.status = status


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    final_url: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", tuple(self.headers))

    def header(self, name: str) -> str:
        lowered = name.lower()
        return next((value for key, value in self.headers if key.lower() == lowered), "")


class HttpTransport(Protocol):
    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse: ...


class UrllibTransport:
    def __init__(self, *, user_agent: str = "Mozilla/5.0 ZodiacV2/1.0") -> None:
        self.user_agent = user_agent

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip"})
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
                result = HttpResponse(
                    int(response.status),
                    response.geturl(),
                    body,
                    tuple(response.headers.items()),
                )
        except HTTPError as exc:
            body = exc.read(max_bytes + 1)
            result = HttpResponse(exc.code, exc.geturl(), body, tuple(exc.headers.items()))
        except (URLError, OSError, IncompleteRead) as exc:
            raise SourceFetchError(SourceFetchCode.NETWORK, f"HTTP 请求失败：{exc}", url=url) from exc
        if len(result.body) > max_bytes:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, f"HTTP 响应超过 {max_bytes} 字节", url=url)
        return result


class RequestsTransport:
    def __init__(
        self,
        *,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        insecure_tls_hosts: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        self.user_agent = user_agent
        if insecure_tls_hosts:
            raise ValueError("已移除不校验 TLS 的站点白名单；请修复证书或配置受信任 CA")

    def _request(
        self,
        url: str,
        *,
        timeout: float,
        max_bytes: int,
        verify: bool,
    ) -> HttpResponse:
        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                    "Accept-Encoding": "gzip",
                }
            )
            if not verify:
                raise ValueError("HTTP 取源禁止关闭 TLS 证书校验")
            with session.get(url, timeout=timeout, stream=True, verify=True) as response:
                response.raw.decode_content = False
                body = response.raw.read(max_bytes + 1)
                return HttpResponse(
                    int(response.status_code), response.url, body, tuple(response.headers.items()),
                )

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        try:
            result = self._request(url, timeout=timeout, max_bytes=max_bytes, verify=True)
        except requests.RequestException as exc:
            raise SourceFetchError(SourceFetchCode.NETWORK, f"HTTP 请求失败：{exc}", url=url) from exc
        if len(result.body) > max_bytes:
            raise SourceFetchError(SourceFetchCode.TOO_LARGE, f"HTTP 响应超过 {max_bytes} 字节", url=url)
        return result


class ResilientHttpTransport:
    def __init__(self, primary: HttpTransport, fallback: HttpTransport) -> None:
        self.primary = primary
        self.fallback = fallback

    def request(self, url: str, *, timeout: float, max_bytes: int) -> HttpResponse:
        deadline = monotonic() + timeout

        def fallback_request() -> HttpResponse:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise SourceFetchError(
                    SourceFetchCode.NETWORK,
                    f"HTTP 取源总超时 {timeout:g}秒",
                    url=url,
                )
            return self.fallback.request(url, timeout=remaining, max_bytes=max_bytes)

        try:
            result = self.primary.request(url, timeout=timeout, max_bytes=max_bytes)
        except SourceFetchError as exc:
            if exc.code is not SourceFetchCode.NETWORK:
                raise
            return fallback_request()
        if result.status in TRANSIENT_HTTP_STATUSES:
            return fallback_request()
        return result


def default_http_transport() -> HttpTransport:
    return ResilientHttpTransport(
        UrllibTransport(),
        RequestsTransport(insecure_tls_hosts=DEFAULT_INSECURE_TLS_HOSTS),
    )


def _decompressed_body(response: HttpResponse, max_bytes: int, url: str) -> bytes:
    encoding = response.header("Content-Encoding").lower().strip()
    if not encoding:
        body = response.body
    elif encoding == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(response.body)) as stream:
                body = stream.read(max_bytes + 1)
        except (OSError, EOFError) as exc:
            raise SourceFetchError(SourceFetchCode.DECODE, f"gzip 解码失败：{exc}", url=url) from exc
    else:
        raise SourceFetchError(SourceFetchCode.DECODE, f"不支持的 Content-Encoding：{encoding}", url=url)
    if len(body) > max_bytes:
        raise SourceFetchError(SourceFetchCode.TOO_LARGE, f"解码后正文超过 {max_bytes} 字节", url=url)
    return body


def _decode_body(body: bytes, content_type: str, url: str) -> str:
    charset_match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type, re.IGNORECASE)
    declared = charset_match.group(1) if charset_match else ""
    if declared:
        try:
            return body.decode(declared)
        except LookupError as exc:
            raise SourceFetchError(
                SourceFetchCode.DECODE,
                f"未知的声明编码：{declared}",
                url=url,
            ) from exc
        except UnicodeDecodeError:
            pass
    encodings = tuple(encoding for encoding in ("utf-8-sig", "gb18030", "big5") if encoding != declared)
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    if declared.lower() in {"gb2312", "gbk", "gb18030", "big5", "big5-hkscs"}:
        decoded = body.decode("gb18030", errors="replace")
        replacements = decoded.count("\ufffd")
        if replacements <= 64 and replacements / max(1, len(decoded)) <= 0.001:
            return decoded
    raise SourceFetchError(SourceFetchCode.DECODE, "无法按声明或常用中文编码解码正文", url=url)


def fetch_http_document(
    transport: HttpTransport,
    url: str,
    *,
    timeout: float = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
    identity_url: str | None = None,
    document_type: DocumentType | None = None,
    priority: int = 0,
    source_id: str | None = None,
    page_order: int = 0,
) -> SourceDocument:
    try:
        source_identity(url)
        response = transport.request(url, timeout=timeout, max_bytes=max_bytes)
        final_identity = validate_final_url(identity_url or url, response.final_url)
    except SourceIdentityError as exc:
        raise SourceFetchError(SourceFetchCode.SOURCE_IDENTITY, str(exc), url=url) from exc
    if not 200 <= response.status < 300:
        raise SourceFetchError(
            SourceFetchCode.HTTP_STATUS,
            f"HTTP 状态码 {response.status}",
            url=url,
            status=response.status,
        )
    if len(response.body) > max_bytes:
        raise SourceFetchError(SourceFetchCode.TOO_LARGE, f"HTTP 响应超过 {max_bytes} 字节", url=url)
    content_type = response.header("Content-Type")
    body = _decompressed_body(response, max_bytes, url)
    text = _decode_body(body, content_type, url)
    resolved_type = document_type or (
        DocumentType.JSON if "json" in content_type.lower() else DocumentType.HTML
    )
    resolved_source_id = source_id or f"{resolved_type.value}:{response.final_url}"
    return SourceDocument(
        text,
        response.final_url,
        resolved_type,
        priority,
        resolved_source_id,
        page_order,
        final_identity.topic_id or final_identity.article_id,
    )