from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from zodiac_v2.cache import cache_records, validate_cache_data
from zodiac_v2.contracts import CacheRecord, FailureCode, RunMode, ScrapeResult, SiteConfig
from zodiac_v2.duplicate import DuplicateMatch, find_duplicate_matches
from zodiac_v2.services.scrape import cache_record_from_result
from zodiac_v2.source.documents import same_source_identity


class SiteScraper(Protocol):
    def scrape_site(self, site: SiteConfig, period: int, mode: RunMode) -> ScrapeResult: ...


@dataclass(frozen=True, slots=True)
class OnboardingDecision:
    accepted: bool
    reasons: tuple[str, ...]
    results: tuple[ScrapeResult, ...]
    duplicate_matches: tuple[DuplicateMatch, ...]


_HISTORICAL_ABSENCE_CODES = frozenset(
    {FailureCode.PERIOD, FailureCode.DEDICATED_PARSER_MISS}
)


def _configuration_conflicts(candidate: SiteConfig, existing: Iterable[SiteConfig]) -> tuple[str, ...]:
    sites = tuple(existing)
    candidate_name = candidate.name.strip()
    name_conflicts = tuple(
        f"站名重名：{candidate_name} 已对应 {site.url}"
        for site in sites
        if site.name.strip() == candidate_name
    )
    if name_conflicts:
        return tuple(dict.fromkeys(name_conflicts))

    reasons: list[str] = []
    for site in sites:
        if same_source_identity(site.url, candidate.url):
            reasons.append(f"URL/topic 重复：{candidate.url} 已属于 {site.name}")
    return tuple(dict.fromkeys(reasons))


def validate_new_site(
    scraper: SiteScraper,
    candidate: SiteConfig,
    existing_sites: Iterable[SiteConfig],
    recent_cache_data: object,
    periods: Iterable[int],
    *,
    allow_short_history: bool = False,
) -> OnboardingDecision:
    conflicts = _configuration_conflicts(candidate, existing_sites)
    if conflicts:
        return OnboardingDecision(False, conflicts, (), ())
    selected_periods = tuple(dict.fromkeys(periods))
    if not selected_periods:
        return OnboardingDecision(
            False,
            ("新增站点验收没有提供期数基准",),
            (),
            (),
        )
    try:
        validated_cache = validate_cache_data(recent_cache_data)
    except ValueError as exc:
        return OnboardingDecision(False, (f"正式近10期判重未完成：{exc}",), (), ())
    latest_period = validated_cache.get("latest_period")
    if not isinstance(latest_period, int):
        return OnboardingDecision(False, ("正式近10期缓存缺少 latest_period",), (), ())
    allowed_baselines = {latest_period}
    if latest_period > 1:
        allowed_baselines.add(latest_period - 1)
    if selected_periods[0] not in allowed_baselines:
        return OnboardingDecision(
            False,
            (
                f"新增站点验收基准期只允许正式缓存最新{latest_period}期"
                f"或上一期{latest_period - 1}期",
            ),
            (),
            (),
        )
    if selected_periods != tuple(sorted(selected_periods, reverse=True)):
        return OnboardingDecision(
            False,
            ("新增站点验收期数必须按倒序提供",),
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
    unavailable = tuple(
        result
        for result in results
        if not result.ok and result.failure_code not in _HISTORICAL_ABSENCE_CODES
    )
    if unavailable:
        reasons = tuple(f"{result.target_period}期：{result.reason}" for result in unavailable)
        return OnboardingDecision(False, reasons, results, ())
    candidate_records: tuple[CacheRecord, ...] = tuple(
        cache_record_from_result(result)
        for result in results
        if result.ok and result.candidate is not None
    )
    if not candidate_records:
        return OnboardingDecision(
            False,
            ("候选站没有任何有效期号，重复检测未完成",),
            results,
            (),
        )
    if len(candidate_records) < 10 and not allow_short_history:
        return OnboardingDecision(
            False,
            (f"候选站只有{len(candidate_records)}期有效历史，默认准入要求10期",),
            results,
            (),
        )
    baseline_records = cache_records(validated_cache)
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
            ("正式缓存与候选站没有共同已有期号，重复检测未完成",),
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
                (suspected, f"共同已有期号中3至5期相同，疑似重复，暂停人工审核：{suspected}"),
                (confirmed, f"共同已有期号中6期及以上相同，确定重复，禁止加入：{confirmed}"),
            )
            if value
        )
        return OnboardingDecision(False, reasons, results, matches)
    return OnboardingDecision(True, (), results, ())
