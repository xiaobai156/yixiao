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
    for line in text.splitlines():
        match = URL_PATTERN.search(line)
        if match is None:
            continue
        matching = by_url.get(match.group(0), ())
        named = tuple(site for site in matching if line.startswith(f"{site.name} "))
        for site in named or matching:
            if site not in selected:
                selected.append(site)
    return tuple(selected)


def repair_sites(
    scraper: SiteScraper,
    sites: Iterable[SiteConfig],
    target_period: int,
) -> tuple[RepairReport, ...]:
    stage_statuses = tuple(
        f"{stage}:{'已完成' if index < 2 else '待执行'}"
        for index, stage in enumerate(REPAIR_STAGES)
    )
    return tuple(
        RepairReport(
            site,
            target_period,
            scraper.scrape_site(site, target_period, RunMode.READ_ONLY),
            stage_statuses,
        )
        for site in sites
    )
