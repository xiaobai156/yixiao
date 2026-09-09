"""Formal full-batch and targeted commits have deliberately different scopes."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from zodiac_v2.cache import (
    backfill_recent_cache_records,
    load_recent_cache,
    load_recent_cache_for_commit,
    mark_failed_sites,
    update_recent_cache,
    write_recent_cache,
    write_recent_cache_backfill,
)
from zodiac_v2.contracts import ScrapeResult, SiteConfig, SiteSection, WritePermit, build_validation_receipt
from zodiac_v2.output import (
    OutputPaths,
    _OutputPayloads,
    _OUTPUT_TOKEN,
    _read_output_text,
    build_merged_result_payloads,
    build_output_payloads,
    write_output_payloads,
)
from zodiac_v2.storage import locked_paths


def validate_result_scope(
    results: Iterable[ScrapeResult],
    expected_sites: Iterable[SiteConfig],
    permit: WritePermit,
) -> tuple[ScrapeResult, ...]:
    permit.require_formal_single(permit.target_period)
    expected_rows = tuple(expected_sites)
    rows = tuple(results)
    if not expected_rows or not rows:
        raise ValueError('正式提交范围或结果为空，拒绝覆盖正式文件')
    expected = {site.identity: site for site in expected_rows}
    if len(expected) != len(expected_rows):
        raise ValueError('正式提交配置包含重复站点')
    actual = {}
    for result in rows:
        if result.site.identity in actual:
            raise ValueError(f'正式结果包含重复站点：{result.site.name}')
        if expected.get(result.site.identity) != result.site:
            raise ValueError(f'正式结果不属于本次完整配置：{result.site.name}')
        if result.target_period != permit.target_period:
            raise PermissionError('抓取结果期数与正式许可不一致')
        if result.ok:
            if not result.writable or not result.validator_issued or result.candidate is None:
                raise PermissionError('正式成功必须由统一验证器签发，不能提升只读结果权限')
            receipt = build_validation_receipt(result.site, result.target_period, result.candidate, result.documents)
            if receipt != result.validation_receipt:
                raise PermissionError('抓取结果验证回执不一致')
        actual[result.site.identity] = result
    if actual.keys() != expected.keys():
        raise ValueError(f'正式结果范围不完整：缺少 {len(expected.keys() - actual.keys())} 个站点')
    return tuple(actual[site.identity] for site in expected_rows)


def _section_paths(paths: OutputPaths, section: SiteSection) -> tuple[Path, Path]:
    if section is SiteSection.NEW:
        return paths.new_success, paths.new_failure
    return paths.existing_success, paths.existing_failure


def _cache_issue(reason: str) -> None:
    print(f'缓存更新未完成（不改变本轮实时结果）：{reason}', flush=True)


def _persist_cache(rows: tuple[ScrapeResult, ...], cache_path: Path, permit: WritePermit, *, targeted: bool) -> None:
    from zodiac_v2.services.scrape import cache_record_from_result

    successes = tuple(result for result in rows if result.ok)
    if not successes:
        return
    if not targeted and len(successes) * 100 <= len(rows) * 85:
        print(f'成功率 {len(successes)}/{len(rows)} 未超过 85%，缓存不更新', flush=True)
        return
    try:
        if targeted:
            data, quarantined = load_recent_cache(cache_path), {}
        else:
            data, quarantined = load_recent_cache_for_commit(cache_path)
    except (ValueError, OSError) as exc:
        _cache_issue(f'缓存读取失败：{exc}')
        return
    latest = data.get('latest_period')
    older = isinstance(latest, int) and permit.target_period < latest
    if older and not targeted:
        _cache_issue(f'禁止把缓存最新期 {latest} 回滚至 {permit.target_period}')
        return
    by_identity = {
        (entry['name'], entry['url'], entry.get('pick', entry.get('region')), entry.get('section', SiteSection.EXISTING.value)): entry
        for entry in data['sites']
    }
    records = []
    for result in successes:
        if result.site.identity in quarantined:
            _cache_issue(f'{result.site.name} 已隔离：{quarantined[result.site.identity]}')
            continue
        entry = by_identity.get(result.site.identity)
        if older and entry is None:
            _cache_issue(f'{result.site.name} 没有旧期回填所需的既有身份')
            continue
        old_values = {item['period']: item['zodiac'] for item in entry.get('records', [])} if entry else {}
        old = old_values.get(permit.target_period)
        if old is not None and old != result.candidate.zodiac:
            _cache_issue(f'{result.site.name} 缓存同期冲突：旧值 {old}，新值 {result.candidate.zodiac}，旧值保留')
            continue
        records.append(cache_record_from_result(result))
    if not records:
        return
    try:
        if older:
            updated = backfill_recent_cache_records(data, records, permit=permit)
            write_recent_cache_backfill(cache_path, updated, permit)
        else:
            updated = update_recent_cache(data, records, current_period=permit.target_period, permit=permit)
            failures = tuple((result.site.identity, result.reason) for result in rows if not result.ok)
            if failures and not targeted:
                updated = mark_failed_sites(updated, failures, current_period=permit.target_period, permit=permit)
            write_recent_cache(cache_path, updated, permit)
    except (OSError, ValueError, PermissionError) as exc:
        _cache_issue(str(exc))
        return
    print(f'缓存已更新：{len(records)}/{len(successes)} 个成功站点', flush=True)


def commit_full_formal_single(
    results: Iterable[ScrapeResult], *, expected_sites: Iterable[SiteConfig],
    cache_path: Path, paths: OutputPaths, permit: WritePermit,
    existing_success_extra_names: Iterable[str] = (),
) -> tuple[ScrapeResult, ...]:
    rows = validate_result_scope(results, expected_sites, permit)
    payloads = build_output_payloads(rows, paths, existing_success_extra_names=existing_success_extra_names)
    with locked_paths((*payloads, cache_path)):
        write_output_payloads(payloads, permit)
        _persist_cache(rows, cache_path, permit, targeted=False)
    return rows


def commit_targeted_formal_single(
    results: Iterable[ScrapeResult], *, expected_sites: Iterable[SiteConfig],
    cache_path: Path, paths: OutputPaths, permit: WritePermit,
) -> tuple[ScrapeResult, ...]:
    rows = validate_result_scope(results, expected_sites, permit)
    selected_paths = tuple(dict.fromkeys(path for result in rows for path in _section_paths(paths, result.site.section)))
    with locked_paths((*selected_paths, cache_path)):
        texts = {path: _read_output_text(path) for path in selected_paths}
        changed: dict[Path, str | None] = {}
        for result in rows:
            partial = build_merged_result_payloads(result, paths, permit, texts=texts)
            changed.update(partial)
            texts.update({path: text for path, text in partial.items() if text is not None})
        # Preflight every target before publishing any: later conflicts cannot partly commit.
        payloads = _OutputPayloads(changed, target_period=permit.target_period, token=_OUTPUT_TOKEN)
        write_output_payloads(payloads, permit)
        _persist_cache(rows, cache_path, permit, targeted=True)
    return rows
