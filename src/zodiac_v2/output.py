from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from zodiac_v2.contracts import FailureCode, ScrapeResult, SiteSection, WritePermit
from zodiac_v2.storage import atomic_write_many, locked_paths, require_no_pending_transaction

_OUTPUT_TOKEN = object()


class _OutputPayloads(Mapping[Path, str | None]):
    __slots__ = ("_target_period", "_values", "_token", "_journal_path")

    def __init__(
        self,
        values: Mapping[Path, str | None],
        *,
        target_period: int,
        token: object,
        journal_path: Path,
    ) -> None:
        if token is not _OUTPUT_TOKEN:
            raise PermissionError("输出载荷必须由统一验证器签发")
        self._values = dict(values)
        self._target_period = target_period
        self._token = token
        self._journal_path = journal_path

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
    if isinstance(period, bool) or not isinstance(period, int) or not 1 <= period <= 9999:
        raise ValueError("输出期数必须是 1 到 9999 的整数")
    return OutputPaths(
        success_dir / f"{period}期-肖.txt",
        success_dir / f"{period}期-肖-新增.txt",
        failure_dir / f"{period}期-肖-失败.txt",
        failure_dir / f"{period}期-肖-失败-新增.txt",
    )


def output_journal(paths: OutputPaths, period: int) -> Path:
    return paths.existing_success.parent / f".zodiac-v2-{period}-output-transaction.json"


def all_output_paths(paths: OutputPaths) -> tuple[Path, ...]:
    return (paths.existing_success, paths.new_success, paths.existing_failure, paths.new_failure)


def _validated_results(results: Iterable[ScrapeResult]) -> tuple[ScrapeResult, ...]:
    rows = tuple(results)
    if not rows:
        raise ValueError("正式输出结果为空，拒绝覆盖正式文件")
    identities: set[tuple[object, ...]] = set()
    names: set[tuple[SiteSection, str]] = set()
    for result in rows:
        if not isinstance(result, ScrapeResult):
            raise ValueError("正式输出只能包含 ScrapeResult")
        key = (result.site.section, _output_name_key(result.site.name))
        if result.site.identity in identities or key in names:
            raise ValueError(f"正式输出包含重复站点：{result.site.name}")
        identities.add(result.site.identity)
        names.add(key)
        if result.ok and (not result.writable or not result.validator_issued):
            raise PermissionError("正式输出只接受统一验证器签发结果")
    return rows


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
    materialized = _validated_results(results)
    if len({path.resolve() for path in all_output_paths(paths)}) != 4:
        raise PermissionError("四类输出文件路径必须互不重叠")
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
    if len(path_periods) != 1 or any(re.match(r"^(\d+)期-", name) is None for name in path_names):
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
        journal_path=output_journal(paths, target_period),
    )


def write_output_payloads(payloads: _OutputPayloads, permit: WritePermit) -> None:
    if not isinstance(payloads, _OutputPayloads) or payloads._token is not _OUTPUT_TOKEN:
        raise PermissionError("输出载荷必须由统一验证器签发")
    permit.require_formal_single(payloads._target_period)
    expected_prefix = f"{permit.target_period}期-"
    if not payloads or any(not path.name.startswith(expected_prefix) for path in payloads):
        raise PermissionError("输出文件期数与正式单期写入许可不一致")
    atomic_write_many(
        {path: text.encode("utf-8") if text is not None else None for path, text in payloads.items()},
        journal=payloads._journal_path,
    )


def _read_output_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "无\n"


def _success_rows(text: str, separator: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == separator:
            break
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and parts[0] in ZODIAC_ORDER:
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
        if len(parts) == 2 and parts[0] in ZODIAC_ORDER:
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
    rank_by_count = {
        count: rank for rank, count in enumerate(sorted(set(counter.values()), reverse=True), start=1)
    }
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
                f"{zodiac}\t{counter[zodiac]}\t{rank_by_count[counter[zodiac]]}"
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


def _merged_success_text(
    text: str,
    results: tuple[ScrapeResult, ...],
    section: SiteSection,
    *,
    allow_existing_value_correction: bool,
) -> str:
    """Edit selected raw detail lines, preserving unrelated text and its order."""
    lines = text.splitlines()
    ranking = next((index for index, line in enumerate(lines)
                    if line.strip() == "生肖次数排行榜" or line.split() == ["内容", "次数", "排名"]), len(lines))
    statistics = next((index for index, line in enumerate(lines)
                       if line.strip() == "前一期失败统计"), len(lines))
    details = lines[:min(ranking, statistics)]
    if not details or all(not line.strip() or line.strip() == "无" for line in details):
        details = ["红色" if section is SiteSection.NEW else "羽墨"]
    while details and not details[-1].strip():
        details.pop()
    for result in results:
        if not result.ok or result.candidate is None:
            continue
        target_key = _output_name_key(result.site.name)
        indexes = []
        for index, line in enumerate(details):
            parts = line.split(maxsplit=1)
            if (len(parts) == 2 and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER
                    and _output_name_key(parts[1]) == target_key):
                indexes.append(index)
        old_values = {details[index].split(maxsplit=1)[0] for index in indexes}
        if old_values and old_values != {result.candidate.zodiac}:
            if not allow_existing_value_correction:
                raise ValueError(f"成功TXT已有不同值，禁止覆盖：{result.site.name} "
                                 f"{sorted(old_values)} -> {result.candidate.zodiac}")
            for index in indexes:
                details[index] = f"{result.candidate.zodiac} {result.site.name}"
        if not indexes:
            details.append(f"{result.candidate.zodiac} {result.site.name}")
    counter: Counter[str] = Counter()
    for line in details:
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 1 and parts[0] in ZODIAC_ORDER:
            counter[parts[0]] += 1
    ranks = {count: rank for rank, count in enumerate(sorted(set(counter.values()), reverse=True), 1)}
    ranked = [f"{value}\t{counter[value]}\t{ranks[counter[value]]}"
              for value in sorted(counter, key=lambda item: (-counter[item], ZODIAC_ORDER.index(item)))]
    tail = lines[statistics:] if statistics < len(lines) else ["前一期失败统计", "无"]
    return "\n".join([*details, "", "内容\t次数\t排名", *ranked, "", *tail]) + "\n"


def build_merged_output_payloads(
    results: Iterable[ScrapeResult],
    paths: OutputPaths,
    permit: WritePermit,
    *,
    allow_existing_value_correction: bool = False,
) -> _OutputPayloads:
    """Build all selected changes before writing any; caller holds output locks."""
    rows = _validated_results(results)
    permit.require_formal_single(permit.target_period)
    if any(result.target_period != permit.target_period for result in rows):
        raise PermissionError("抓取结果期数与正式单期写入许可不一致")
    values: dict[Path, str | None] = {}
    for section in SiteSection:
        selected = tuple(result for result in rows if result.site.section is section)
        if not selected:
            continue
        success_path = paths.new_success if section is SiteSection.NEW else paths.existing_success
        failure_path = paths.new_failure if section is SiteSection.NEW else paths.existing_failure
        if any(not path.name.startswith(f"{permit.target_period}期-") for path in (success_path, failure_path)):
            raise PermissionError("输出文件期数与正式单期写入许可不一致")
        # A failed retry does not revoke an earlier verified success, or rewrite its file.
        if any(result.ok for result in selected):
            values[success_path] = _merged_success_text(
                _read_output_text(success_path), selected, section,
                allow_existing_value_correction=allow_existing_value_correction,
            )
        failures = _failure_rows(_read_output_text(failure_path))
        for result in selected:
            target_prefix = f"{result.site.name} {result.site.direction.value} "
            failures = [row for row in failures if not row.startswith(target_prefix)]
            if not result.ok:
                failures.append(_target_failure_row(result))
        values[failure_path] = _format_failure_rows(failures)
    return _OutputPayloads(values, target_period=permit.target_period, token=_OUTPUT_TOKEN,
                           journal_path=output_journal(paths, permit.target_period))


def merge_formal_results_output(
    results: Iterable[ScrapeResult], paths: OutputPaths, permit: WritePermit, *,
    allow_existing_value_correction: bool = False,
) -> None:
    rows = _validated_results(results)
    journal = output_journal(paths, permit.target_period)
    with locked_paths((*all_output_paths(paths), journal)):
        require_no_pending_transaction(journal)
        payloads = build_merged_output_payloads(
            rows, paths, permit, allow_existing_value_correction=allow_existing_value_correction,
        )
        write_output_payloads(payloads, permit)


def merge_formal_single_result_output(
    result: ScrapeResult, paths: OutputPaths, permit: WritePermit, *,
    allow_existing_value_correction: bool = False,
) -> None:
    """Compatibility entry point for one authorized targeted update."""
    merge_formal_results_output(
        (result,), paths, permit, allow_existing_value_correction=allow_existing_value_correction,
    )
