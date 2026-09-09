from __future__ import annotations

import os
import re
import threading
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from zodiac_v2.contracts import FailureCode, ScrapeResult, SiteSection, WritePermit
from zodiac_v2.storage import atomic_batch_write, locked_paths, path_key

_OUTPUT_TOKEN = object()


class _OutputPayloads(Mapping[Path, str | None]):
    __slots__ = ("_target_period", "_values", "_token")

    def __init__(
        self,
        values: Mapping[Path, str | None],
        *,
        target_period: int,
        token: object,
    ) -> None:
        if token is not _OUTPUT_TOKEN:
            raise PermissionError("输出载荷必须由统一验证器签发")
        self._values = dict(values)
        self._target_period = target_period
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
    FailureCode.HTTP_STATUS: "HTTP状态失败",
    FailureCode.BROWSER_UNAVAILABLE: "浏览器不可用",
    FailureCode.BROWSER_CAPTURE: "浏览器取源失败",
    FailureCode.PARSER_ERROR: "解析器异常",
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
    if isinstance(period, bool) or not isinstance(period, int) or not 1 <= period <= 9999:
        raise ValueError("输出期数必须是正整数")
    return OutputPaths(
        success_dir / f"{period}期-肖.txt",
        success_dir / f"{period}期-肖-新增.txt",
        failure_dir / f"{period}期-肖-失败.txt",
        failure_dir / f"{period}期-肖-失败-新增.txt",
    )


def _success_text(
    results: Iterable[ScrapeResult],
    section: SiteSection,
    *,
    extra_names: Iterable[str] = (),
) -> str:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[object, ...]] = set()
    for result in results:
        if not result.ok or result.candidate is None or result.site.section is not section:
            continue
        key = (*result.site.identity, result.target_period, result.candidate.zodiac)
        if key in seen:
            continue
        seen.add(key)
        rows.append((result.candidate.zodiac, result.site.name))
    return _format_success_rows(rows, section, extra_names=extra_names)


def _failure_text(results: Iterable[ScrapeResult], section: SiteSection) -> str:
    failed = [result for result in results if not result.ok and result.site.section is section]
    if not failed:
        return "无\n"
    rows: list[str] = []
    for result in failed:
        label = FAILURE_LABELS[result.failure_code or FailureCode.OTHER]
        rows.append(
            f"{result.site.name} {result.site.direction.value} {result.site.url} "
            f"原因：[{label}] {result.reason}"
        )
    return _format_failure_rows(rows)


def build_output_payloads(
    results: Iterable[ScrapeResult],
    paths: OutputPaths,
    *,
    existing_success_extra_names: Iterable[str] = (),
) -> _OutputPayloads:
    materialized = tuple(results)
    if not materialized:
        raise ValueError("正式输出结果为空，拒绝覆盖")
    identities = [result.site.identity for result in materialized]
    if len(set(identities)) != len(identities):
        raise ValueError("正式输出包含重复站点，禁止同站多值")
    output_files = (paths.existing_success, paths.new_success, paths.existing_failure, paths.new_failure)
    if len({path_key(path) for path in output_files}) != 4:
        raise PermissionError("四类输出路径不能重复")
    if any(result.ok and not result.validator_issued for result in materialized):
        raise PermissionError("正式输出只接受统一验证器签发结果")
    path_names = tuple(
        path.name
        for path in (
            paths.existing_success,
            paths.new_success,
            paths.existing_failure,
            paths.new_failure,
        )
    )
    path_periods = {
        int(match.group(1))
        for name in path_names
        if (match := re.match(r"^(\d+)期-", name)) is not None
    }
    if len(path_periods) != 1:
        raise PermissionError("四类输出文件必须绑定同一期数")
    target_period = next(iter(path_periods))
    if any(result.target_period != target_period for result in materialized):
        raise PermissionError("抓取结果期数与输出文件期数不一致")
    return _OutputPayloads(
        {
        paths.existing_success: _success_text(
            materialized,
            SiteSection.EXISTING,
            extra_names=existing_success_extra_names,
        ),
        paths.new_success: _success_text(materialized, SiteSection.NEW),
        paths.existing_failure: _failure_text(materialized, SiteSection.EXISTING),
        paths.new_failure: _failure_text(materialized, SiteSection.NEW),
        },
        target_period=target_period,
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
    permit.require_formal_single(payloads._target_period)
    if any(not path.name.startswith(f"{permit.target_period}期-") for path in payloads):
        raise PermissionError("输出文件期数与正式单期写入许可不一致")
    atomic_batch_write({path: text.encode("utf-8") if text is not None else None for path, text in payloads.items()})


def _read_output_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return "无\n"


def _success_rows(text: str, separator: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == separator:
            break
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER:
            rows.append((parts[0], parts[1]))
    return rows


def _success_extra_names(text: str, separator: str) -> list[str]:
    extras: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == separator:
            break
        parts = stripped.split(maxsplit=1)
        if len(parts) == 1 and stripped != "无" and stripped not in extras:
            extras.append(stripped)
    return extras


def _trailing_success_rows(text: str, separator: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    after_separator = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "生肖次数排行榜" or stripped.split() == ["内容", "次数", "排名"]:
            break
        if stripped == separator:
            after_separator = True
            continue
        if not after_separator or not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER:
            rows.append((parts[0], parts[1]))
    return rows


def _format_success_rows(
    rows: Iterable[tuple[str, str]],
    section: SiteSection,
    *,
    extra_names: Iterable[str] = (),
    trailing_rows: Iterable[tuple[str, str]] = (),
) -> str:
    materialized = tuple(rows)
    trailing = tuple(trailing_rows)
    all_rows = (*materialized, *trailing)
    successful_names = {name for _zodiac, name in all_rows}
    extras: list[str] = []
    for name in extra_names:
        normalized = str(name).strip()
        if normalized and normalized not in successful_names and normalized not in extras:
            extras.append(normalized)
    if not all_rows and not extras:
        return "无\n"
    counter: Counter[str] = Counter(zodiac for zodiac, _name in all_rows)
    ranks = {count: rank for rank, count in enumerate(sorted(set(counter.values()), reverse=True), 1)}
    separator = "红色" if section is SiteSection.NEW else "羽墨"
    lines = [f"{zodiac} {name}" for zodiac, name in materialized]
    lines.extend(extras)
    lines.append(separator)
    lines.extend(f"{zodiac} {name}" for zodiac, name in trailing)
    lines.extend(
        [
            "",
            "内容\t次数\t排名",
            *(
                f"{zodiac}\t{counter[zodiac]}\t{ranks[counter[zodiac]]}"
                for zodiac in sorted(counter, key=lambda item: (-counter[item], ZODIAC_ORDER.index(item)))
            ),
            "",
            "前一期失败统计",
            "无",
        ]
    )
    return "\n".join(lines) + "\n"


def _failure_rows(text: str) -> list[str]:
    rows: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "失败分类统计":
            break
        if stripped and stripped != "无":
            rows.append(stripped)
    return rows


_FAILURE_LABEL = re.compile(r"原因：\[([^\]]+)\]")
_INVISIBLE_NAME_CHARACTERS = re.compile(r"[\u200b-\u200d\ufeff]")


def _output_name_key(value: str) -> str:
    return _INVISIBLE_NAME_CHARACTERS.sub("", value).strip()




def _is_success_detail_row(value: str) -> tuple[str, str] | None:
    parts = value.split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER and parts[1].strip():
        return parts[0], parts[1].strip()
    return None


def _validate_existing_success_text(text: str, separator: str) -> None:
    """Reject lossy targeted rewrites when the existing detail section is not understood."""
    separator_seen = False
    meaningful = False
    empty_marker_only = True
    names: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "生肖次数排行榜" or stripped.split() == ["内容", "次数", "排名"]:
            break
        if not stripped:
            continue
        meaningful = True
        if stripped == "无":
            continue
        empty_marker_only = False
        if stripped == separator:
            if separator_seen:
                raise ValueError(f"成功TXT包含重复分隔符：{separator}")
            separator_seen = True
            continue
        row = _is_success_detail_row(stripped)
        if row is not None:
            zodiac, name = row
            key = _output_name_key(name)
            if key in names:
                raise ValueError(f"成功TXT存在重复站点明细，拒绝有损重写：{name}")
            names[key] = zodiac
            continue
        if not separator_seen and len(stripped.split()) == 1:
            # Historical extra-name rows such as 华林 are valid before the section separator.
            continue
        raise ValueError(f"成功TXT包含无法识别的明细行，拒绝有损重写：{stripped}")
    if meaningful and not empty_marker_only and not separator_seen:
        raise ValueError(f"成功TXT缺少分隔符 {separator}，拒绝有损重写")


_FAILURE_ROW_IDENTITY = re.compile(r"^(?P<name>.+?)\s+(?:top|bottom)\s+https?://\S+\s+原因：")


def _failure_name_key(row: str) -> str | None:
    match = _FAILURE_ROW_IDENTITY.match(row.strip())
    return _output_name_key(match.group("name")) if match is not None else None

def _format_failure_rows(rows: Iterable[str]) -> str:
    materialized = tuple(rows)
    if not materialized:
        return "无\n"
    counter: Counter[str] = Counter()
    for row in materialized:
        match = _FAILURE_LABEL.search(row)
        if match is not None:
            counter[match.group(1)] += 1
    lines: list[str] = []
    for index, row in enumerate(materialized):
        if index:
            lines.append("")
        lines.append(row)
    lines.extend(("", "失败分类统计"))
    lines.extend(
        f"{label} {counter[label]}条"
        for label in FAILURE_LABELS.values()
        if counter[label]
    )
    return "\n".join(lines) + "\n"


def _target_failure_row(result: ScrapeResult) -> str:
    label = FAILURE_LABELS.get(result.failure_code or FailureCode.OTHER, "其他失败")
    return (
        f"{result.site.name} {result.site.direction.value} {result.site.url} "
        f"原因：[{label}] {result.reason}"
    )


def build_merged_result_payloads(
    result: ScrapeResult,
    paths: OutputPaths,
    permit: WritePermit,
    *,
    allow_existing_value_correction: bool = False,
    texts: Mapping[Path, str] | None = None,
) -> _OutputPayloads:
    """Merge one repaired result, preserving unrelated rows and their order."""
    permit.require_formal_single(permit.target_period)
    if result.target_period != permit.target_period:
        raise PermissionError("抓取结果期数与正式单期写入许可不一致")
    if result.ok and (not result.writable or not result.validator_issued):
        raise PermissionError("正式成功结果未获得统一验证器写入资格")

    is_new = result.site.section is SiteSection.NEW
    success_path = paths.new_success if is_new else paths.existing_success
    failure_path = paths.new_failure if is_new else paths.existing_failure
    expected_prefix = f"{permit.target_period}期-"
    if not success_path.name.startswith(expected_prefix) or not failure_path.name.startswith(expected_prefix):
        raise PermissionError("输出文件期数与正式单期写入许可不一致")

    separator = "红色" if is_new else "羽墨"
    read_text = _read_output_text if texts is None else lambda path: texts[path]
    existing_success_text = read_text(success_path)
    _validate_existing_success_text(existing_success_text, separator)
    success_rows = _success_rows(existing_success_text, separator)
    trailing_success_rows = _trailing_success_rows(existing_success_text, separator)
    success_extra_names = _success_extra_names(existing_success_text, separator)
    target_name_key = _output_name_key(result.site.name)
    all_success_rows = (*success_rows, *trailing_success_rows)
    target_indexes = [
        index
        for index, (_zodiac, name) in enumerate(all_success_rows)
        if _output_name_key(name) == target_name_key
    ]
    if result.ok and result.candidate is not None:
        target_row = (result.candidate.zodiac, result.site.name)
        existing_zodiacs = {all_success_rows[index][0] for index in target_indexes}
        if (
            existing_zodiacs
            and existing_zodiacs != {result.candidate.zodiac}
            and not allow_existing_value_correction
        ):
            raise ValueError(
                f"成功TXT已有不同值，禁止覆盖：{result.site.name} "
                f"{sorted(existing_zodiacs)} -> {result.candidate.zodiac}"
            )
        if existing_zodiacs and existing_zodiacs != {result.candidate.zodiac}:
            for index in target_indexes:
                if index < len(success_rows):
                    success_rows[index] = target_row
                else:
                    trailing_success_rows[index - len(success_rows)] = target_row
        if not target_indexes:
            trailing_success_rows.append(target_row)

    failure_rows = _failure_rows(read_text(failure_path))
    failure_rows = [row for row in failure_rows if _failure_name_key(row) != target_name_key]
    if not result.ok:
        failure_rows.append(_target_failure_row(result))

    payloads = _OutputPayloads(
        {
            success_path: _format_success_rows(
                success_rows,
                result.site.section,
                extra_names=success_extra_names,
                trailing_rows=trailing_success_rows,
            ),
            failure_path: _format_failure_rows(failure_rows),
        },
        target_period=result.target_period,
        token=_OUTPUT_TOKEN,
    )
    if not result.ok:
        # Do not even normalize an existing success file after a failed retry.
        return _OutputPayloads({failure_path: payloads[failure_path]}, target_period=result.target_period, token=_OUTPUT_TOKEN)
    return payloads


def merge_formal_single_result_output(result, paths, permit, *, allow_existing_value_correction=False) -> None:
    pair = (paths.new_success, paths.new_failure) if result.site.section is SiteSection.NEW else (paths.existing_success, paths.existing_failure)
    with locked_paths(pair):
        payloads = build_merged_result_payloads(result, paths, permit, allow_existing_value_correction=allow_existing_value_correction)
        write_output_payloads(payloads, permit)
