from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from zodiac_v2.contracts import RunMode, ScrapeResult, SiteConfig
from zodiac_v2.source.documents import same_source_identity

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
    known = {site.name: site for site in sites}
    selected = []
    for line in text.splitlines():
        if URL_PATTERN.search(line) is None:
            continue
        match = re.match(r"^(?P<name>.+?)\s+(?P<pick>top|bottom)\s+(?P<url>https?://\S+)", line.strip())
        if match is None:
            raise ValueError(f"失败清单行缺少明确站名/方向：{line}")
        name = re.sub(r"[\u200b-\u200d\ufeff]", "", match['name']).strip()
        site = known.get(name)
        if site is None or site.direction.value != match['pick'] or not same_source_identity(site.url, match['url']):
            raise ValueError(f"失败清单身份与当前配置不一致，拒绝扩大复抓范围：{name}")
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
