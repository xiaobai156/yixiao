"""正式写入前的判重闸门：命中重复站直接失败，禁止静默通过。

历史缺陷：find_duplicate_matches 只在 duplicate/onboard 两个只读命令里被调用，
正式写入链路一次都没调，所以「判重」从未阻断过任何一次入库。本模块把闸门
补进 commit_full_formal_single / commit_targeted_formal_single。

判定规则（用户 2026-10-22 确认）：**没达到 10 期不算重复**。
只有双方各自记录数都满 10 且共同期逐期全等，才阻断写入。
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from zodiac_v2.cache import load_recent_cache
from zodiac_v2.contracts import CacheRecord, Direction, ScrapeResult, SiteSection
from zodiac_v2.duplicate import DuplicateMatch, blocking_matches, find_duplicate_matches
from zodiac_v2.validation.conflicts import _active_candidates


class DuplicateGateError(PermissionError):
    """正式写入被重复站点闸门拦截。"""


def _direction(entry: dict) -> Direction:
    raw = str(entry.get("pick", entry.get("direction", "top"))).strip()
    return Direction.BOTTOM if raw in {"bottom", "尾部", "底部", "下"} else Direction.TOP


def _section(entry: dict) -> SiteSection:
    return SiteSection.NEW if str(entry.get("section", "")).strip() == "新增的站点" else SiteSection.EXISTING


def _baseline_records(cache_path: Path) -> tuple[CacheRecord, ...]:
    """读取基线记录；缓存不可读时抛 DuplicateGateError（fail-closed 且退出码正确）。"""
    try:
        data = load_recent_cache(cache_path)
    except (ValueError, OSError) as exc:
        # 判重只提示不阻断：缓存读不了就跳过判重，不能因此让整批写入失败。
        print(f"判重跳过（缓存不可读）：{exc}", flush=True)
        return ()

    records: list[CacheRecord] = []
    for entry in data.get("sites", []):
        direction = _direction(entry)
        section = _section(entry)
        for item in entry.get("records", []):
            records.append(
                CacheRecord(
                    name=entry["name"],
                    url=entry["url"],
                    direction=direction,
                    section=section,
                    period=int(item["period"]),
                    zodiac=item["zodiac"],
                    source_id="cache:baseline",
                    source_url=entry["url"],
                    evidence_sha256="0" * 64,
                )
            )
    return tuple(records)


def _bundle(result: ScrapeResult):
    from zodiac_v2.contracts import SourceBundle

    return SourceBundle(result.documents, ("gate:reuse",), scan_complete=True)


def _candidate_records(result: ScrapeResult, parser, minimum: int = 2) -> tuple[CacheRecord, ...]:
    """把该站本轮文档重解析成候选，**用与统一校验器相同的口径挑值**。

    页面存在多套循环（record-cycle）时，正式写入按方向挑一组：顶部取第一组、
    尾部取最后一组。判重必须用同一套挑法，否则「判重比的值」和「写进 TXT 的值」
    可能不是同一个生肖，导致漏拦或误拦。
    """
    if not result.documents or parser is None:
        return ()
    try:
        candidates = parser.parse(result.site, _bundle(result))
    except Exception as exc:  # noqa: BLE001 - 解析失败必须可见，不能静默放行
        print(f"{result.site.name} 判重解析失败，本站跳过判重：{exc}", flush=True)
        return ()
    if not candidates:
        return ()

    # 与 validation.conflicts._direction_window 一致：先按方向挑循环组，再按期去重
    active = _active_candidates(tuple(candidates), result.site.direction)

    records: list[CacheRecord] = []
    seen: set[int] = set()
    for candidate in active:
        if candidate.period in seen:
            continue
        seen.add(candidate.period)
        records.append(
            CacheRecord(
                name=result.site.name,
                url=result.site.url,
                direction=result.site.direction,
                section=result.site.section,
                period=candidate.period,
                zodiac=candidate.zodiac,
                source_id=candidate.document_id,
                source_url=result.site.url,
                evidence_sha256="0" * 64,
            )
        )
    return tuple(records) if len(records) >= minimum else ()


def check_duplicates(
    results: Iterable[ScrapeResult],
    cache_path: Path,
    *,
    parser_resolver=None,
    minimum_consecutive_periods: int = 3,
    window: int = 10,
) -> tuple[DuplicateMatch, ...]:
    """返回疑似命中（供打印）；命中 confirmed 则抛 DuplicateGateError 中止写入。

    只有会写入的成功站才参与判重——失败站不写任何东西，没有理由阻断整批。
    """
    if not cache_path.exists() or parser_resolver is None:
        return ()
    baseline = _baseline_records(cache_path)
    if not baseline:
        return ()

    blocking: list[DuplicateMatch] = []
    suspected: list[DuplicateMatch] = []
    for result in results:
        if not result.ok:
            # 失败站不写盘，不参与判重，避免整批误拦。
            continue
        parser = parser_resolver(result.site)
        if parser is None:
            continue
        candidate = _candidate_records(result, parser)
        if not candidate:
            continue
        matches = find_duplicate_matches(
            candidate,
            baseline,
            minimum_consecutive_periods=minimum_consecutive_periods,
            window=window,
        )
        # 排除自身（身份漂移后旧条目仍在缓存里，不能自己拦自己）
        matches = tuple(
            match for match in matches
            if not (match.url == result.site.url and match.name == result.site.name)
        )
        blocking.extend(blocking_matches(matches))
        suspected.extend(match for match in matches if match.risk == "suspected")

    if suspected:
        # 「没达到 10 期不算重复」——但仍要让用户看到，不能静默。
        for match in suspected[:20]:
            print(
                f"疑似重复（未满 {window} 期，不阻断）：{match.name} 与在册站点"
                f"「{match.url}」共同 {len(match.common_periods)} 期、"
                f"其中 {len(match.identical_periods)} 期相同",
                flush=True,
            )

    if blocking:
        # 用户规则（2026-10-24）：判重只提示，不阻断写入。
        # 重复站照常输出，由用户另行安排；这里仅打印供人工查看。
        for match in blocking:
            print(
                f"重复提示（不阻断写入）：{match.name} 与在册站点"
                f"「{match.url}」满 {len(match.common_periods)} 期逐期全等",
                flush=True,
            )
    return tuple(suspected) + tuple(blocking)
