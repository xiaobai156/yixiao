"""Separate full snapshots from explicitly scoped repairs.

Fetching is finished before this module is called. TXT and cache have separate
outcomes: a cache failure never turns a validated live result into a failure.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from zodiac_v2.cache import (
    _identity as cache_entry_identity,
    _validated_quarantined_sites,
    load_recent_cache,
    load_recent_cache_for_commit,
    mark_failed_sites,
    update_recent_cache,
    write_recent_cache,
)
from zodiac_v2.contracts import ScrapeResult, SiteConfig, WritePermit, build_validation_receipt
from zodiac_v2.output import (
    OutputPaths,
    _validated_results,
    all_output_paths,
    build_merged_output_payloads,
    build_output_payloads,
    output_journal,
    write_output_payloads,
)
from zodiac_v2.storage import locked_paths, require_no_pending_transaction

CACHE_SUCCESS_RATE_PERCENT = 85


def validate_exact_scope(
    results: Iterable[ScrapeResult],
    expected_sites: Iterable[SiteConfig],
    permit: WritePermit,
) -> tuple[ScrapeResult, ...]:
    permit.require_formal_single(permit.target_period)
    expected_rows = tuple(expected_sites)
    if not expected_rows or any(not isinstance(site, SiteConfig) for site in expected_rows):
        raise ValueError("正式提交必须提供非空的预期站点集合")
    expected = {site.identity: site for site in expected_rows}
    if len(expected) != len(expected_rows):
        raise ValueError("预期站点集合包含重复身份")
    rows = _validated_results(results)
    actual = {result.site.identity for result in rows}
    if actual != set(expected):
        missing = set(expected) - actual
        extra = actual - set(expected)
        raise ValueError(f"正式提交范围不完整：缺少 {len(missing)} 个，额外 {len(extra)} 个")
    for result in rows:
        if result.target_period != permit.target_period:
            raise PermissionError("抓取结果期数与正式单期写入许可不一致")
        if result.site != expected[result.site.identity]:
            raise ValueError(f"抓取结果配置与预期配置不一致：{result.site.name}")
        if result.ok and result.candidate is not None:
            receipt = build_validation_receipt(
                result.site, result.target_period, result.candidate, result.documents,
            )
            if receipt != result.validation_receipt:
                raise PermissionError("抓取结果缺少有效统一验证回执")
    return rows


def _report_cache_issue(reason: str) -> None:
    print(f"缓存更新未完成（不影响本轮实时抓取结果）：{reason}", flush=True)


def _update_cache(
    rows: tuple[ScrapeResult, ...], cache_path: Path, permit: WritePermit, *, targeted: bool,
) -> None:
    # This import is local to avoid a source-service / persistence-service cycle.
    from zodiac_v2.services.scrape import cache_record_from_result

    successes = tuple(result for result in rows if result.ok)
    if not successes:
        return
    if not targeted and len(successes) * 100 <= len(rows) * CACHE_SUCCESS_RATE_PERCENT:
        print(f"成功率 {len(successes)}/{len(rows)} 未超过 85%，缓存不更新", flush=True)
        return
    try:
        if targeted:
            # A repair must not automatically quarantine or rewrite unrelated
            # malformed cache entries. Leave the entire cache unchanged instead.
            data = load_recent_cache(cache_path)
            quarantined = _validated_quarantined_sites(data)
        else:
            data, quarantined = load_recent_cache_for_commit(cache_path)
        latest = data.get("latest_period")
        if isinstance(latest, int) and permit.target_period < latest:
            raise ValueError(f"缓存不能从 {latest}期 回滚到 {permit.target_period}期；旧期回填需单独授权")
        # Index once, preflight per-site conflicts once, then validate/copy the
        # entire cache once for the batch rather than once for each success.
        by_identity = {cache_entry_identity(entry): entry for entry in data["sites"]}
        records = []
        for result in successes:
            identity = result.site.identity
            if identity in quarantined:
                _report_cache_issue(f"{result.site.name} 缓存目录已隔离：{quarantined[identity]}")
                continue
            entry = by_identity.get(identity)
            previous = next(
                (row["zodiac"] for row in entry.get("records", ()) if row["period"] == permit.target_period),
                None,
            ) if entry is not None else None
            if previous is not None and previous != result.candidate.zodiac:
                _report_cache_issue(
                    f"缓存同期冲突：{result.site.name} {permit.target_period}期旧值 {previous}，"
                    f"新值 {result.candidate.zodiac}；未覆盖旧缓存"
                )
                continue
            records.append(cache_record_from_result(result))
        failures = tuple((r.site.identity, r.reason) for r in rows if not r.ok) if not targeted else ()
        if not records and not failures:
            return
        updated = update_recent_cache(
            data, records, current_period=permit.target_period, permit=permit,
        ) if records else data
        # A full snapshot revokes current-period failures when its gate passes.
        # A repair failure is only a failed attempt, not a revocation of history.
        if failures:
            updated = mark_failed_sites(
                updated, failures, current_period=permit.target_period, permit=permit,
            )
        write_recent_cache(cache_path, updated, permit)
    except (OSError, ValueError, RuntimeError) as exc:
        _report_cache_issue(str(exc))


def _commit(
    results: Iterable[ScrapeResult], *, expected_sites: Iterable[SiteConfig],
    cache_path: Path, paths: OutputPaths, permit: WritePermit, targeted: bool,
    existing_success_extra_names: Iterable[str] = (),
) -> tuple[ScrapeResult, ...]:
    rows = validate_exact_scope(results, expected_sites, permit)
    journal = output_journal(paths, permit.target_period)
    if cache_path.resolve() in {path.resolve() for path in (*all_output_paths(paths), journal)}:
        raise ValueError("缓存路径不能与正式 TXT 或事务日志重合")
    # Hold the same locks before loading old TXT and cache, not just at replace.
    with locked_paths((*all_output_paths(paths), cache_path, journal)):
        require_no_pending_transaction(journal)
        if targeted:
            payloads = build_merged_output_payloads(rows, paths, permit)
        else:
            payloads = build_output_payloads(
                rows, paths, existing_success_extra_names=existing_success_extra_names,
            )
        write_output_payloads(payloads, permit)
        _update_cache(rows, cache_path, permit, targeted=targeted)
    return rows


def commit_full_formal_single(
    results: Iterable[ScrapeResult], *, expected_sites: Iterable[SiteConfig],
    cache_path: Path, paths: OutputPaths, permit: WritePermit,
    existing_success_extra_names: Iterable[str] = (),
) -> tuple[ScrapeResult, ...]:
    return _commit(
        results, expected_sites=expected_sites, cache_path=cache_path, paths=paths,
        permit=permit, targeted=False, existing_success_extra_names=existing_success_extra_names,
    )


def commit_targeted_formal_single(
    results: Iterable[ScrapeResult], *, expected_sites: Iterable[SiteConfig],
    cache_path: Path, paths: OutputPaths, permit: WritePermit,
) -> tuple[ScrapeResult, ...]:
    return _commit(
        results, expected_sites=expected_sites, cache_path=cache_path, paths=paths,
        permit=permit, targeted=True,
    )


def commit_formal_single(
    results: Iterable[ScrapeResult], *, cache_path: Path, paths: OutputPaths,
    permit: WritePermit, expected_sites: Iterable[SiteConfig] | None = None,
    existing_success_extra_names: Iterable[str] = (),
) -> tuple[ScrapeResult, ...]:
    """Compatibility name; missing explicit full scope must fail closed."""
    if expected_sites is None:
        raise ValueError("全量正式提交必须显式提供 expected_sites；定点复抓请使用定点提交接口")
    return commit_full_formal_single(
        results, expected_sites=expected_sites, cache_path=cache_path, paths=paths,
        permit=permit, existing_success_extra_names=existing_success_extra_names,
    )
