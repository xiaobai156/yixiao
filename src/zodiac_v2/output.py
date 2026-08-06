from __future__ import annotations

import os
import threading
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from zodiac_v2.contracts import FailureCode, ScrapeResult, SiteSection, WritePermit

_OUTPUT_TOKEN = object()


class _OutputPayloads(Mapping[Path, str | None]):
    __slots__ = ("_values", "_token")

    def __init__(self, values: Mapping[Path, str | None], *, token: object) -> None:
        if token is not _OUTPUT_TOKEN:
            raise PermissionError("输出载荷必须由统一验证器签发")
        self._values = dict(values)
        self._token = token

    def __getitem__(self, path: Path) -> str | None:
        return self._values[path]

    def __iter__(self) -> Iterator[Path]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

ZODIAC_ORDER = "牛马羊鸡狗猪鼠虎兔龙蛇猴"
FAILURE_LABELS = {
    FailureCode.NETWORK: "网络失败",
    FailureCode.PERIOD: "期数失败",
    FailureCode.DIRECTION: "方向失败",
    FailureCode.ANCHOR: "锚点失败",
    FailureCode.FIELD: "字段失败",
    FailureCode.CONFLICT: "候选冲突",
    FailureCode.BOUNDARY: "边界失败",
    FailureCode.SOURCE_IDENTITY: "来源身份失败",
    FailureCode.DEDICATED_PARSER_MISS: "专属解析未命中",
    FailureCode.CACHE_CONFLICT: "缓存同期冲突",
    FailureCode.OTHER: "其他失败",
}


@dataclass(frozen=True, slots=True)
class OutputPaths:
    existing_success: Path
    new_success: Path
    existing_failure: Path
    new_failure: Path


def output_paths(period: int, success_dir: Path, failure_dir: Path) -> OutputPaths:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("输出期数必须是正整数")
    return OutputPaths(
        success_dir / f"{period}期-肖.txt",
        success_dir / f"{period}期-肖-新增.txt",
        failure_dir / f"{period}期-肖-失败.txt",
        failure_dir / f"{period}期-肖-失败-新增.txt",
    )


def _success_text(results: Iterable[ScrapeResult], section: SiteSection) -> str:
    rows: list[str] = []
    seen: set[tuple[object, ...]] = set()
    counter: Counter[str] = Counter()
    for result in results:
        if not result.ok or result.candidate is None or result.site.section is not section:
            continue
        key = (*result.site.identity, result.target_period, result.candidate.zodiac)
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"{result.candidate.zodiac} {result.site.name}")
        counter[result.candidate.zodiac] += 1
    if not rows:
        return "无\n"
    rank = [
        f"{zodiac} {counter[zodiac]}次"
        for zodiac in sorted(counter, key=lambda item: (-counter[item], ZODIAC_ORDER.index(item)))
    ]
    separator = ["红色", ""] if section is SiteSection.NEW else ["羽墨", ""]
    lines = rows + separator + ["生肖次数排行榜"] + rank + ["", "前一期失败统计", "无"]
    return "\n".join(lines) + "\n"


def _failure_text(results: Iterable[ScrapeResult], section: SiteSection) -> str:
    failed = [result for result in results if not result.ok and result.site.section is section]
    if not failed:
        return "无\n"
    lines: list[str] = []
    counter: Counter[str] = Counter()
    for result in failed:
        label = FAILURE_LABELS[result.failure_code or FailureCode.OTHER]
        counter[label] += 1
        if lines:
            lines.append("")
        lines.append(
            f"{result.site.name} {result.site.direction.value} {result.site.url} "
            f"原因：[{label}] {result.reason}"
        )
    lines.extend(["", "失败分类统计"])
    for label in FAILURE_LABELS.values():
        if counter[label]:
            lines.append(f"{label} {counter[label]}条")
    return "\n".join(lines) + "\n"


def build_output_payloads(
    results: Iterable[ScrapeResult],
    paths: OutputPaths,
) -> _OutputPayloads:
    materialized = tuple(results)
    if any(result.ok and not result.validator_issued for result in materialized):
        raise PermissionError("正式输出只接受统一验证器签发结果")
    return _OutputPayloads(
        {
        paths.existing_success: _success_text(materialized, SiteSection.EXISTING),
        paths.new_success: _success_text(materialized, SiteSection.NEW),
        paths.existing_failure: _failure_text(materialized, SiteSection.EXISTING),
        paths.new_failure: _failure_text(materialized, SiteSection.NEW),
        },
        token=_OUTPUT_TOKEN,
    )


def _stage(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def write_output_payloads(payloads: _OutputPayloads, permit: WritePermit) -> None:
    if not isinstance(payloads, _OutputPayloads) or payloads._token is not _OUTPUT_TOKEN:
        raise PermissionError("输出载荷必须由统一验证器签发")
    permit.require_formal_single(permit.target_period)
    expected_prefix = f"{permit.target_period}期-"
    if any(not path.name.startswith(expected_prefix) for path in payloads):
        raise PermissionError("输出文件期数与正式单期写入许可不一致")
    originals = {path: path.read_bytes() if path.exists() else None for path in payloads}
    staged: dict[Path, Path] = {}
    try:
        staged = {path: _stage(path, text) for path, text in payloads.items() if text is not None}
        for path, text in payloads.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(staged[path], path)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
