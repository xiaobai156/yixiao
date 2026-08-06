from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from zodiac_v2.cache import cache_records
from zodiac_v2.contracts import CacheRecord, RunMode, ScrapeResult, SiteConfig, SiteSection
from zodiac_v2.duplicate import DuplicateMatch, find_duplicate_matches
from zodiac_v2.services.scrape import cache_record_from_result


class SiteScraper(Protocol):
    def scrape_site(self, site: SiteConfig, period: int, mode: RunMode) -> ScrapeResult: ...


@dataclass(frozen=True, slots=True)
class OnboardingDecision:
    accepted: bool
    reasons: tuple[str, ...]
    results: tuple[ScrapeResult, ...]
    duplicate_matches: tuple[DuplicateMatch, ...]


def _configuration_conflicts(candidate: SiteConfig, existing: Iterable[SiteConfig]) -> tuple[str, ...]:
    reasons: list[str] = []
    for site in existing:
        if site.name == candidate.name:
            reasons.append(f"站名重名：{candidate.name} 已对应 {site.url}")
        if site.url == candidate.url:
            reasons.append(f"URL/topic 重复：{candidate.url} 已属于 {site.name}")
    if candidate.section is not SiteSection.NEW:
        reasons.append("新增站点必须属于新增的站点分类")
    return tuple(dict.fromkeys(reasons))


def validate_new_site(
    scraper: SiteScraper,
    candidate: SiteConfig,
    existing_sites: Iterable[SiteConfig],
    recent_cache_data: object,
    periods: Iterable[int],
    *,
    required_periods: int = 10,
) -> OnboardingDecision:
    conflicts = _configuration_conflicts(candidate, existing_sites)
    if conflicts:
        return OnboardingDecision(False, conflicts, (), ())
    selected_periods = tuple(dict.fromkeys(periods))
    if len(selected_periods) != required_periods:
        return OnboardingDecision(
            False,
            (f"近10期有效数据不足：需要 {required_periods} 期，实际 {len(selected_periods)} 期",),
            (),
            (),
        )
    expected_periods = tuple(range(selected_periods[0], selected_periods[0] - required_periods, -1))
    if selected_periods != expected_periods:
        return OnboardingDecision(
            False,
            ("近10期历史必须按连续期号倒序提供，缺失期不得跨越拼接",),
            (),
            (),
        )
    live_result = scraper.scrape_site(candidate, selected_periods[0], RunMode.READ_ONLY)
    if not live_result.ok:
        return OnboardingDecision(
            False,
            (f"{live_result.target_period}期实时方向验证失败：{live_result.reason}",),
            (live_result,),
            (),
        )
    historical_results = getattr(scraper, "historical_results", None)
    if callable(historical_results):
        results = tuple(historical_results(candidate, selected_periods, live_result))
    else:
        results = (
            live_result,
            *(
                scraper.scrape_site(candidate, period, RunMode.READ_ONLY)
                for period in selected_periods[1:]
            ),
        )
    if tuple(result.target_period for result in results) != selected_periods:
        return OnboardingDecision(
            False,
            ("历史提取返回的期号、数量或原始顺序与验收窗口不一致",),
            results,
            (),
        )
    failed = tuple(result for result in results if not result.ok)
    if failed:
        reasons = tuple(f"{result.target_period}期：{result.reason}" for result in failed)
        return OnboardingDecision(False, reasons, results, ())
    candidate_records: tuple[CacheRecord, ...] = tuple(cache_record_from_result(result) for result in results)
    try:
        baseline_records = cache_records(recent_cache_data)
    except ValueError as exc:
        return OnboardingDecision(False, (f"正式近10期判重未完成：{exc}",), results, ())
    if not baseline_records:
        return OnboardingDecision(
            False,
            ("正式近10期缓存没有统一验证记录，重复检测未完成",),
            results,
            (),
        )
    candidate_periods = {record.period for record in candidate_records}
    baseline_periods = {record.period for record in baseline_records}
    if not candidate_periods & baseline_periods:
        return OnboardingDecision(
            False,
            ("正式近10期缓存与候选站没有共同期号，重复检测未完成",),
            results,
            (),
        )
    matches = find_duplicate_matches(
        candidate_records,
        baseline_records,
        minimum_consecutive_periods=3,
    )
    if matches:
        suspected = "/".join(match.name for match in matches if match.risk == "suspected")
        confirmed = "/".join(match.name for match in matches if match.risk == "confirmed")
        reasons = tuple(
            reason
            for value, reason in (
                (suspected, f"连续3至5期相同，疑似重复，暂停人工审核：{suspected}"),
                (confirmed, f"连续6期及以上相同，确定重复，禁止加入：{confirmed}"),
            )
            if value
        )
        return OnboardingDecision(False, reasons, results, matches)
    return OnboardingDecision(True, (), results, ())
