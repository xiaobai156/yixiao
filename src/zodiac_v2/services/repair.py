from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from zodiac_v2.contracts import RunMode, ScrapeResult, SiteConfig

REPAIR_STAGES = (
    "登记",
    "复现",
    "实验策略",
    "严格验证",
    "只读校验",
    "同步",
    "回归复审",
    "正式验收",
)
URL_PATTERN = re.compile(r"https?://\S+")


class SiteScraper(Protocol):
    def scrape_site(self, site: SiteConfig, period: int, mode: RunMode) -> ScrapeResult: ...


@dataclass(frozen=True, slots=True)
class RepairReport:
    site: SiteConfig
    target_period: int
    result: ScrapeResult
    stages: tuple[str, ...]


def sites_from_failure_text(text: str, sites: Iterable[SiteConfig]) -> tuple[SiteConfig, ...]:
    by_url: dict[str, list[SiteConfig]] = {}
    for site in sites:
        by_url.setdefault(site.url, []).append(site)
    selected: list[SiteConfig] = []
    for raw_line in text.splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        match = URL_PATTERN.search(line)
        if match is None:
            continue
        matching = by_url.get(match.group(0), ())
        prefix = line[:match.start()].strip()
        named = tuple(
            site for site in matching
            if prefix == f"{site.name} {site.direction.value}"
        )
        if prefix:
            matching = named
        if len(matching) != 1:
            raise ValueError(f"失败行不能唯一匹配配置站点（{len(matching)} 个）：{line}")
        site = matching[0]
        if site not in selected:
            selected.append(site)
    return tuple(selected)


def repair_sites(
    scraper: SiteScraper,
    sites: Iterable[SiteConfig],
    target_period: int,
    *,
    timeout: float = 60.0,
    workers: int = 1,
) -> tuple[RepairReport, ...]:
    stage_statuses = tuple(
        f"{stage}:{'已完成' if index < 2 else '待执行'}"
        for index, stage in enumerate(REPAIR_STAGES)
    )
    selected = tuple(sites)
    batch = getattr(scraper, "scrape_sites", None)
    if callable(batch):
        results = batch(
            selected, target_period, RunMode.READ_ONLY, timeout=timeout, workers=workers,
        )
    else:
        if workers != 1 or timeout != 60.0:
            raise ValueError("此只读抓取器不支持 workers/timeout；不能静默忽略参数")
        results = tuple(scraper.scrape_site(site, target_period, RunMode.READ_ONLY) for site in selected)
    return tuple(
        RepairReport(result.site, target_period, result, stage_statuses)
        for result in results
    )
