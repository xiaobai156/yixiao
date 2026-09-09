from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

try:
    from enum import StrEnum as StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.10 implementation matching the Python 3.11 string-enum contract."""

        def __new__(cls, *values: object) -> StrEnum:
            if len(values) > 3:
                raise TypeError(f"too many arguments for str(): {values!r}")
            if len(values) == 1 and not isinstance(values[0], str):
                raise TypeError(f"{values[0]!r} is not a string")
            if len(values) >= 2 and not isinstance(values[1], str):
                raise TypeError(f"encoding must be a string, not {values[1]!r}")
            if len(values) == 3 and not isinstance(values[2], str):
                raise TypeError(f"errors must be a string, not {values[2]!r}")
            value = str(*values)
            member = str.__new__(cls, value)
            member._value_ = value
            return member

        __str__ = str.__str__
        __format__ = str.__format__

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
            return name.lower()


ZODIACS = frozenset("牛马羊鸡狗猪鼠虎兔龙蛇猴")


class Direction(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"


class SiteSection(StrEnum):
    EXISTING = "已有站点"
    NEW = "新增的站点"


class DocumentType(StrEnum):
    HTML = "html"
    JSON = "json"
    BROWSER = "browser"
    SCRIPT = "script"
    IFRAME = "iframe"


class FailureCode(StrEnum):
    NETWORK = "network"
    HTTP_STATUS = "http_status"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    BROWSER_CAPTURE = "browser_capture"
    PARSER_ERROR = "parser_error"
    PERIOD = "period"
    DIRECTION = "direction"
    ANCHOR = "anchor"
    FIELD = "field"
    CONFLICT = "conflict"
    BOUNDARY = "boundary"
    SOURCE_IDENTITY = "source_identity"
    DEDICATED_PARSER_MISS = "dedicated_parser_miss"
    CACHE_CONFLICT = "cache_conflict"
    OTHER = "other"


class RunMode(StrEnum):
    READ_ONLY = "read_only"
    FORMAL_SINGLE = "formal_single"


_VALIDATION_TOKEN = object()


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} 不能为空")
    return normalized


def _period(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9999:
        raise ValueError("期数必须是 1 到 9999 的整数")
    return value


def _page_order(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("页面顺序必须是非负整数")
    return value


def _zodiac(value: str) -> str:
    normalized = value.strip()
    if len(normalized) != 1 or normalized not in ZODIACS:
        raise ValueError(f"生肖必须是单个合法生肖：{value!r}")
    return normalized


def _optional_record_id(value: str | None, field: str = "record_id") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串或 None")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} 不能为空字符串")
    return normalized


def _infer_source_record_id(url: str) -> str | None:
    match = re.search(
        r"/(?:topic/|article/(?:admin|manager|lottery)/|article/ar_content/id/|"
        r"api/proxy/(?:admin-articles|manager-articles)/)([a-z0-9]+)",
        url,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class SiteConfig:
    name: str
    url: str
    direction: Direction
    section: SiteSection
    parser_id: str
    source_policy: str
    api_url: str | None = None
    article_keyword: str | None = None
    embedded_max_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "url", _required_text(self.url, "url"))
        object.__setattr__(self, "parser_id", _required_text(self.parser_id, "parser_id"))
        object.__setattr__(self, "source_policy", _required_text(self.source_policy, "source_policy"))
        if not isinstance(self.direction, Direction):
            raise ValueError("direction 必须是 Direction")
        if not isinstance(self.section, SiteSection):
            raise ValueError("section 必须是 SiteSection")
        if self.api_url is not None:
            object.__setattr__(self, "api_url", _required_text(self.api_url, "api_url"))
        if self.article_keyword is not None:
            object.__setattr__(
                self,
                "article_keyword",
                _required_text(self.article_keyword, "article_keyword"),
            )
        if (
            self.embedded_max_bytes is not None
            and (
                isinstance(self.embedded_max_bytes, bool)
                or not isinstance(self.embedded_max_bytes, int)
                or self.embedded_max_bytes <= 0
            )
        ):
            raise ValueError("embedded_max_bytes 必须是正整数或 None")

    @property
    def identity(self) -> tuple[str, str, Direction, SiteSection]:
        return (self.name, self.url, self.direction, self.section)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    text: str
    final_url: str
    document_type: DocumentType
    priority: int
    source_id: str
    page_order: int
    record_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "final_url", _required_text(self.final_url, "final_url"))
        object.__setattr__(self, "source_id", _required_text(self.source_id, "source_id"))
        if not isinstance(self.document_type, DocumentType):
            raise ValueError("document_type 必须是 DocumentType")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or self.priority < 0:
            raise ValueError("priority 必须是非负整数")
        _page_order(self.page_order)
        object.__setattr__(
            self,
            "record_id",
            _optional_record_id(self.record_id) or _infer_source_record_id(self.final_url),
        )


@dataclass(frozen=True, slots=True)
class SourceBundle:
    documents: tuple[SourceDocument, ...]
    diagnostics: tuple[str, ...] = ()
    scan_complete: bool = True

    def __init__(
        self,
        documents: Iterable[SourceDocument],
        diagnostics: Iterable[str] = (),
        *,
        scan_complete: bool = True,
    ) -> None:
        object.__setattr__(self, "documents", tuple(documents))
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "scan_complete", scan_complete)
        if any(not isinstance(document, SourceDocument) for document in self.documents):
            raise ValueError("documents 只能包含 SourceDocument")
        if any(not isinstance(item, str) or not item.strip() for item in self.diagnostics):
            raise ValueError("diagnostics 只能包含非空字符串")
        if not isinstance(scan_complete, bool):
            raise ValueError("scan_complete 必须是布尔值")


@dataclass(frozen=True, slots=True)
class Candidate:
    period: int
    zodiac: str
    raw_line: str
    document_id: str
    page_order: int
    evidence: tuple[str, ...]
    record_id: str | None = None

    def __init__(
        self,
        period: int,
        zodiac: str,
        raw_line: str,
        document_id: str,
        page_order: int,
        evidence: Iterable[str],
        *,
        record_id: str | None = None,
    ) -> None:
        object.__setattr__(self, "period", _period(period))
        object.__setattr__(self, "zodiac", _zodiac(zodiac))
        object.__setattr__(self, "raw_line", _required_text(raw_line, "raw_line"))
        object.__setattr__(self, "document_id", _required_text(document_id, "document_id"))
        object.__setattr__(self, "page_order", _page_order(page_order))
        evidence_tuple = tuple(_required_text(item, "evidence") for item in evidence)
        if not evidence_tuple:
            raise ValueError("evidence 不能为空")
        object.__setattr__(self, "evidence", evidence_tuple)
        object.__setattr__(self, "record_id", _optional_record_id(record_id))


def build_validation_receipt(
    site: SiteConfig,
    target_period: int,
    candidate: Candidate,
    documents: Iterable[SourceDocument],
) -> str:
    payload = {
        "site": {
            "name": site.name,
            "url": site.url,
            "direction": site.direction.value,
            "section": site.section.value,
            "parser_id": site.parser_id,
            "source_policy": site.source_policy,
            "api_url": site.api_url,
            "article_keyword": site.article_keyword,
            "embedded_max_bytes": site.embedded_max_bytes,
        },
        "target_period": target_period,
        "candidate": {
            "period": candidate.period,
            "zodiac": candidate.zodiac,
            "raw_line": candidate.raw_line,
            "document_id": candidate.document_id,
            "page_order": candidate.page_order,
            "evidence": candidate.evidence,
            "record_id": candidate.record_id,
        },
        "documents": [
            {
                "source_id": document.source_id,
                "final_url": document.final_url,
                "document_type": document.document_type.value,
                "priority": document.priority,
                "page_order": document.page_order,
                "record_id": document.record_id,
                "text_sha256": hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
            }
            for document in sorted(documents, key=lambda item: (item.page_order, item.source_id))
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    candidate: Candidate | None
    failure_code: FailureCode | None
    reason: str

    def __post_init__(self) -> None:
        if self.failure_code is not None and not isinstance(self.failure_code, FailureCode):
            raise ValueError("failure_code 必须是 FailureCode")
        if self.candidate is not None:
            if self.failure_code is not None or self.reason:
                raise ValueError("成功候选与失败信息互斥")
            return
        if self.failure_code is None:
            raise ValueError("失败结果必须包含失败代码")
        if not self.reason.strip():
            raise ValueError("失败原因不能为空")

    @classmethod
    def success(cls, candidate: Candidate) -> ValidationDecision:
        return cls(candidate, None, "")

    @classmethod
    def failure(cls, failure_code: FailureCode, reason: str) -> ValidationDecision:
        return cls(None, failure_code, reason)

    @property
    def ok(self) -> bool:
        return self.candidate is not None


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    site: SiteConfig
    target_period: int
    candidate: Candidate | None
    documents: tuple[SourceDocument, ...]
    failure_code: FailureCode | None
    reason: str
    writable: bool
    validation_receipt: str | None = None
    validation_token: object | None = None

    def __post_init__(self) -> None:
        _period(self.target_period)
        object.__setattr__(self, "documents", tuple(self.documents))
        if any(not isinstance(document, SourceDocument) for document in self.documents):
            raise ValueError("documents 只能包含 SourceDocument")
        if self.failure_code is not None and not isinstance(self.failure_code, FailureCode):
            raise ValueError("failure_code 必须是 FailureCode")
        if self.candidate is not None:
            if self.failure_code is not None or self.reason:
                raise ValueError("成功候选与失败信息互斥")
            if self.candidate.period != self.target_period:
                raise ValueError("候选期数必须等于目标期")
            expected_receipt = build_validation_receipt(
                self.site,
                self.target_period,
                self.candidate,
                self.documents,
            )
            if self.validation_receipt is None:
                if self.writable:
                    raise ValueError("正式成功必须包含验证回执")
                object.__setattr__(self, "validation_receipt", expected_receipt)
            elif self.validation_receipt != expected_receipt:
                raise ValueError("验证回执与候选、来源文档不一致")
            if self.writable and self.validation_token is not _VALIDATION_TOKEN:
                raise ValueError("正式成功必须由统一验证器签发")
            if not self.writable and self.validation_token is not None:
                raise ValueError("只读成功不能携带内部验证令牌")
            return
        if self.failure_code is None or not self.reason.strip():
            raise ValueError("失败结果必须包含代码和原因")
        if self.writable:
            raise ValueError("失败结果不能获得写入资格")

    @classmethod
    def success(
        cls,
        site: SiteConfig,
        target_period: int,
        candidate: Candidate,
        documents: Iterable[SourceDocument],
        *,
        writable: bool,
        validation_receipt: str | None = None,
    ) -> ScrapeResult:
        return cls(
            site,
            target_period,
            candidate,
            tuple(documents),
            None,
            "",
            writable,
            validation_receipt,
            None,
        )

    @classmethod
    def _validated_success(
        cls,
        site: SiteConfig,
        target_period: int,
        candidate: Candidate,
        documents: Iterable[SourceDocument],
    ) -> ScrapeResult:
        document_tuple = tuple(documents)
        return cls(
            site,
            target_period,
            candidate,
            document_tuple,
            None,
            "",
            True,
            build_validation_receipt(site, target_period, candidate, document_tuple),
            _VALIDATION_TOKEN,
        )

    @classmethod
    def failure(
        cls,
        site: SiteConfig,
        target_period: int,
        failure_code: FailureCode,
        reason: str,
        documents: Iterable[SourceDocument],
        *,
        writable: bool = False,
    ) -> ScrapeResult:
        return cls(site, target_period, None, tuple(documents), failure_code, reason, writable)

    @property
    def ok(self) -> bool:
        return self.candidate is not None

    @property
    def validator_issued(self) -> bool:
        return self.validation_token is _VALIDATION_TOKEN


@dataclass(frozen=True, slots=True)
class CacheRecord:
    name: str
    url: str
    direction: Direction
    section: SiteSection
    period: int
    zodiac: str
    source_id: str
    source_url: str
    evidence_sha256: str
    record_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("name", "url", "source_id", "source_url"):
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        if not isinstance(self.direction, Direction) or not isinstance(self.section, SiteSection):
            raise ValueError("缓存身份中的方向或分类非法")
        _period(self.period)
        object.__setattr__(self, "zodiac", _zodiac(self.zodiac))
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.evidence_sha256):
            raise ValueError("evidence_sha256 必须是 64 位 SHA-256")
        object.__setattr__(self, "evidence_sha256", self.evidence_sha256.lower())
        object.__setattr__(self, "record_id", _optional_record_id(self.record_id))

    @property
    def identity(self) -> tuple[str, str, Direction, SiteSection]:
        return (self.name, self.url, self.direction, self.section)


@dataclass(frozen=True, slots=True)
class WritePermit:
    target_period: int
    mode: RunMode

    def __post_init__(self) -> None:
        _period(self.target_period)
        if not isinstance(self.mode, RunMode):
            raise ValueError("mode 必须是 RunMode")

    @classmethod
    def formal_single(cls, target_period: int) -> WritePermit:
        return cls(target_period, RunMode.FORMAL_SINGLE)

    def require_formal_single(self, target_period: int) -> None:
        if self.mode is not RunMode.FORMAL_SINGLE:
            raise PermissionError("持久化写入只允许正式单期模式")
        if self.target_period != target_period:
            raise PermissionError(
                f"写入许可期数 {self.target_period} 与目标期数 {target_period} 不一致"
            )
