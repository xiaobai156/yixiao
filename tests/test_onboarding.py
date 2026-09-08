from __future__ import annotations

from zodiac_v2.cli import parse_args
from zodiac_v2.contracts import (
    Candidate,
    Direction,
    DocumentType,
    FailureCode,
    ScrapeResult,
    SiteConfig,
    SiteSection,
    SourceDocument,
)
from zodiac_v2.services.onboarding import _configuration_conflicts, validate_new_site


def _site(name: str, url: str, section: SiteSection = SiteSection.EXISTING) -> SiteConfig:
    return SiteConfig(
        name=name,
        url=url,
        direction=Direction.TOP,
        section=section,
        parser_id="special.test",
        source_policy="http_documents",
    )


def _result(site: SiteConfig, period: int, zodiac: str) -> ScrapeResult:
    source_id = f"html:{site.url}"
    document = SourceDocument(
        f"{period}期 测试栏目【{zodiac}】",
        site.url,
        DocumentType.HTML,
        0,
        source_id,
        0,
        "test-record",
    )
    candidate = Candidate(
        period,
        zodiac,
        document.text,
        source_id,
        0,
        ("title-text:测试栏目",),
        record_id="test-record",
    )
    return ScrapeResult.success(site, period, candidate, (document,), writable=False)


class _FakeScraper:
    def __init__(self, values: dict[int, str | None]) -> None:
        self.values = values
        self.calls: list[int] = []

    def _result(self, site: SiteConfig, period: int) -> ScrapeResult:
        value = self.values.get(period)
        if value is None:
            return ScrapeResult.failure(
                site,
                period,
                FailureCode.PERIOD,
                f"候选中未找到指定 {period}期",
                (),
            )
        return _result(site, period, value)

    def scrape_site(self, site: SiteConfig, period: int, mode) -> ScrapeResult:
        self.calls.append(period)
        return self._result(site, period)

    def historical_results(self, site: SiteConfig, periods, live_result):
        return tuple(self._result(site, period) for period in periods)


def _cache_data(
    periods: dict[int, str],
    *,
    latest_period: int | None = None,
) -> dict[str, object]:
    url = "https://existing.test/site"
    ordered = sorted(periods.items(), reverse=True)
    return {
        "window_back_periods": 10,
        "latest_period": latest_period if latest_period is not None else max(periods),
        "sites": [
            {
                "name": "已有基准站",
                "pick": "top",
                "url": url,
                "section": "已有站点",
                "error": "",
                "records": [
                    {"period": period, "zodiac": zodiac}
                    for period, zodiac in ordered
                ],
                "fingerprint": "".join(zodiac for _period, zodiac in ordered),
                "record_provenance": {
                    str(period): {
                        "validation_status": "validated",
                        "source_id": f"html:{url}",
                        "source_url": url,
                        "evidence_sha256": "a" * 64,
                    }
                    for period, _zodiac in ordered
                },
            }
        ],
        "quarantined_sites": [],
    }


def test_explicit_existing_section_is_allowed_for_onboarding() -> None:
    candidate = SiteConfig(
        name="中性候选站",
        url="https://candidate.test/existing",
        direction=Direction.BOTTOM,
        section=SiteSection.EXISTING,
        parser_id="family.strict_article",
        source_policy="http_documents",
    )

    assert _configuration_conflicts(candidate, ()) == ()


def test_name_conflict_is_checked_before_any_scrape_and_trims_name() -> None:
    candidate = _site(" 候选站 ", "https://candidate.test/name")
    existing = (_site("候选站", "https://existing.test/name"),)
    scraper = _FakeScraper({225: "鼠"})

    decision = validate_new_site(
        scraper,
        candidate,
        existing,
        _cache_data({225: "牛"}),
        (225,),
    )

    assert not decision.accepted
    assert decision.reasons == ("站名重名：候选站 已对应 https://existing.test/name",)
    assert scraper.calls == []


def test_onboarding_accepts_cache_latest_with_ten_periods_and_preserves_new_section() -> None:
    candidate = _site("候选236", "https://candidate.test/236", SiteSection.NEW)
    values = {period: "鼠" for period in range(236, 226, -1)}
    scraper = _FakeScraper(values)

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({period: "牛" for period in values}),
        tuple(values),
    )

    assert decision.accepted
    assert [result.target_period for result in decision.results if result.ok] == list(values)
    assert all(result.site.section is SiteSection.NEW for result in decision.results)


def test_onboarding_accepts_cache_previous_period_with_ten_periods() -> None:
    candidate = _site("候选235", "https://candidate.test/235", SiteSection.EXISTING)
    values = {period: "羊" for period in range(235, 225, -1)}
    scraper = _FakeScraper(values)

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({period: "鼠" for period in range(236, 226, -1)}),
        tuple(values),
    )

    assert decision.accepted
    assert [result.target_period for result in decision.results if result.ok] == list(values)
    assert all(result.site.section is SiteSection.EXISTING for result in decision.results)


def test_onboarding_rejects_baseline_outside_cache_latest_or_previous() -> None:
    candidate = _site("候选234", "https://candidate.test/234")
    scraper = _FakeScraper({234: "羊"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({236: "鼠"}),
        (234,),
    )

    assert not decision.accepted
    assert decision.reasons == ("新增站点验收基准期只允许正式缓存最新236期或上一期235期",)
    assert scraper.calls == []


def test_onboarding_requires_ten_valid_periods_without_explicit_exception() -> None:
    candidate = _site("历史不足", "https://candidate.test/short")
    scraper = _FakeScraper({236: "羊", 235: "狗"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({236: "鼠", 235: "牛"}),
        tuple(range(236, 226, -1)),
    )

    assert not decision.accepted
    assert decision.reasons == ("候选站只有2期有效历史，默认准入要求10期",)


def test_onboarding_short_history_requires_explicit_exception() -> None:
    candidate = _site("历史不足特例", "https://candidate.test/short-special")
    scraper = _FakeScraper({236: "羊", 235: "狗"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({236: "鼠", 235: "牛"}),
        tuple(range(236, 226, -1)),
        allow_short_history=True,
    )

    assert decision.accepted


def test_onboarding_requires_at_least_one_common_existing_period() -> None:
    candidate = _site("无共同期候选", "https://candidate.test/no-common")
    scraper = _FakeScraper({225: "羊"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({224: "鼠"}, latest_period=225),
        (225,),
        allow_short_history=True,
    )

    assert not decision.accepted
    assert decision.reasons == ("正式缓存与候选站没有共同已有期号，重复检测未完成",)


def test_onboarding_duplicate_check_uses_only_common_available_periods() -> None:
    candidate = _site("共同期候选", "https://candidate.test/common")
    scraper = _FakeScraper({225: "鼠", 224: "牛", 223: "虎", 222: "兔"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({225: "鼠", 224: "牛", 223: "虎", 222: "兔"}),
        (225, 224, 223, 222),
        allow_short_history=True,
    )

    assert not decision.accepted
    assert len(decision.duplicate_matches) == 1
    assert decision.duplicate_matches[0].common_periods == (225, 224, 223, 222)
    assert decision.duplicate_matches[0].risk == "suspected"


def test_onboarding_duplicate_check_does_not_bridge_missing_periods() -> None:
    candidate = _site("缺期候选", "https://candidate.test/gap")
    scraper = _FakeScraper({225: "鼠", 223: "虎", 222: "兔"})

    decision = validate_new_site(
        scraper,
        candidate,
        (),
        _cache_data({225: "鼠", 223: "虎", 222: "兔"}),
        (225, 224, 223, 222),
        allow_short_history=True,
    )

    assert decision.accepted
    assert decision.duplicate_matches == ()


def test_onboard_cli_accepts_current_period_bottom_and_defaults_to_new_section() -> None:
    args = parse_args(
        [
            "onboard",
            "--name",
            "顶部候选",
            "--url",
            "https://candidate.test/top",
            "--period",
            "236",
        ]
    )

    assert args.pick == Direction.TOP.value
    assert args.section == SiteSection.NEW.value

    bottom = parse_args(
        [
            "onboard",
            "--name",
            "尾部候选",
            "--url",
            "https://candidate.test/bottom",
            "--pick",
            "bottom",
            "--section",
            SiteSection.EXISTING.value,
            "--period",
            "236",
        ]
    )

    assert bottom.pick == Direction.BOTTOM.value
    assert bottom.section == SiteSection.EXISTING.value


def test_onboarding_detects_same_topic_identity_with_cosmetic_url_difference() -> None:
    candidate = _site("新名称", "https://example.test/topic/123.html?from=new")
    existing = (_site("已有名称", "https://EXAMPLE.test:443/topic/123.html?from=old"),)

    assert _configuration_conflicts(candidate, existing) == (
        "URL/topic 重复：https://example.test/topic/123.html?from=new 已属于 已有名称",
    )
